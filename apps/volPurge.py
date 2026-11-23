# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

volPurge
retenção dos .mvol sincronizados: apaga o .mvol de um volume registrado em
volumes quando ele é mais antigo que --retain-days e já não tem conversão
pendente, e grava has_mvol=0.  É o único lugar que apaga um .mvol local (o
conversor nunca apaga nem move).

- idade pelo horário do volume (volumes.timestamp, nome do .mvol, UTC), não
  pelo mtime: o relógio do servidor não é confiável

- pendente = volume sem produto final no preset ativo; sem a view, status
  fora de DONE/FAILED (vol_dbase.purge_candidates).  Um pendente só é
  apagado depois de --max-days (limite de disco), com aviso no log; sem
  --max-days, nunca

- só apaga arquivo dentro de --sync-dir.  --sync-dir precisa existir e não
  estar vazio: um ponto de montagem desmontado é um diretório vazio, e todo
  .mvol pareceria ausente

- arquivo que já não existe: só corrige has_mvol=0 -- se o diretório dele
  existir (diretório ausente = montagem parcial: não marca, só avisa)

- apaga primeiro e grava o banco depois, numa transação: se a gravação
  falhar, o próximo run acha o arquivo ausente e corrige has_mvol

- sintéticos (status 4/5) e volumes não registrados não são tocados

- guarda de disco (--min-free-gb G): depois da retenção por idade, se o
  sistema de arquivos do --sync-dir tiver menos de G GB livres, apaga os
  .mvol mais antigos até voltar a G -- primeiro os já convertidos, depois
  os pendentes (último recurso, com aviso), nunca um PROCESSING (o
  conversor está lendo).  Disco cheio faria o rsync falhar e perder os
  dados NOVOS, os que mais importam ao nowcast.  Se nem assim chegar a G:
  [error] e rc 1

- limites da guarda de disco: nunca apaga um volume com menos de
  --disk-min-age-hours (default 6 h) -- sem esse piso, um disco cheio por
  outra coisa (sistema de arquivos compartilhado, mínimo mal dimensionado)
  levaria até os volumes recém-chegados, justamente os que a guarda existe
  para proteger; e, com --disk-max-gb, apaga no máximo esse tanto por
  execução: atingido o teto, para com [error] e rc 1, o vol_register.sh não
  grava o heartbeat e o vol_check.sh alerta -- alguém olha antes de a
  guarda consumir o acervo inteiro

uso:
    python volPurge.py <catalog.db> --sync-dir <dir>
                       [--retain-days N [--max-days M]]
                       [--min-free-gb G [--disk-min-age-hours H] [--disk-max-gb X]]
                       [--dry-run]
    (pelo menos um de --retain-days e --min-free-gb)

2026.nov  mlabru  limites da guarda de disco: piso de idade (--disk-min-age-hours,
                  default 6 h) e teto por execução (--disk-max-gb)
2026.nov  mlabru  guarda de disco (--min-free-gb): apaga os mais antigos quando o
                  espaço livre do --sync-dir cai abaixo do mínimo; --retain-days
                  passa a ser opcional (um dos dois é obrigatório)
2026.nov  mlabru  imports cls_common.* (pacote do repo cls.common, via
                  CLS_PYLIB; antes symlinks de diretório)
2026.nov  mlabru  arquivo ausente cujo diretório também sumiu não vira
                  has_mvol=0 (montagem parcial; contador "sem diretório")
2026.out  mlabru  refatoração para legibilidade: purge() dividido em
                  _check_sync_dir, _compute_cutoffs, _purge_one_file,
                  _mark_removed_in_dbase e _log_summary; ternários longos
                  viraram if explícitos
2026.set  mlabru  initial version (Linux/Python)
"""
# < imports >──────────────────────────────────────────────────────────────────────────

# python library
import argparse
import collections
import logging
import pathlib
import shutil
import sqlite3
import sys
import time

# locals
import cls_common.dbase.vol_dbase as vd

# < constants >────────────────────────────────────────────────────────────────────────

# segundos por dia / por hora
MI_DAY_S = 86400
MI_HOUR_S = 3600

# piso de idade da guarda de disco (h): os volumes mais novos que isso nunca
# saem pelo disco.  6 h = 36 volumes por série, a janela que o nowcast usa
MF_DISK_MIN_AGE_H = 6.

# bytes por GB (GiB, como o df -h)
MI_GB = 1024 ** 3

# contadores do resumo
CS_REMOVED = "removidos"
CS_MISSING = "ausentes"
CS_FORCED = "forçados"
CS_OUTSIDE = "fora do sync-dir"
CS_NO_DIR = "sem diretório"
CS_ERROR = "erros"
CS_DISK = "pelo disco"
CS_DISK_SHORT = "disco insuficiente"
CS_DISK_CAP = "teto da guarda"

# ordem dos contadores na linha de resumo do log
MT_SUMMARY_ORDER = (CS_REMOVED, CS_MISSING, CS_FORCED, CS_DISK, CS_OUTSIDE, CS_NO_DIR,
                    CS_ERROR, CS_DISK_SHORT, CS_DISK_CAP)

# < logging >──────────────────────────────────────────────────────────────────────────

# logger
M_LOG = logging.getLogger(__name__)
M_LOG.setLevel(logging.INFO)

# ─────────────────────────────────────────────────────────────────────────────────────
def arg_parse(flst_argv: list | None = None):
    """
    lê e valida os argumentos da linha de comando

    :param flst_argv: argumentos (None = sys.argv; testes passam uma lista)

    :returns: argparse.Namespace com dbase, sync_dir, retain_days, max_days,
              min_free_gb, disk_min_age_hours, disk_max_gb e dry_run
    """
    # logger
    M_LOG.debug(">> arg_parse")

    # create parser
    lparser = argparse.ArgumentParser(
                 description="Apaga os .mvol antigos já convertidos (retenção).")

    lparser.add_argument("dbase", type=str, help="caminho do catalog.db compartilhado.")
    lparser.add_argument("--sync-dir", required=True, type=pathlib.Path,
                         help="raiz dos .mvol sincronizados; nada fora dela é apagado.")
    lparser.add_argument("--retain-days", type=float, default=None,
                         help="idade mínima (dias, pelo horário do volume) para apagar.")
    lparser.add_argument("--max-days", type=float, default=None,
                         help="idade a partir da qual um pendente também é apagado "
                              "(default: nunca).")
    lparser.add_argument("--min-free-gb", type=float, default=None,
                         help="espaço livre mínimo (GB) no sistema de arquivos do "
                              "sync-dir; abaixo dele apaga os mais antigos (default: "
                              "sem guarda de disco).")
    lparser.add_argument("--disk-min-age-hours", type=float, default=MF_DISK_MIN_AGE_H,
                         help="a guarda de disco nunca apaga um volume mais novo que "
                              "isto, em horas (default: %(default)g; 0 = sem piso).")
    lparser.add_argument("--disk-max-gb", type=float, default=None,
                         help="a guarda de disco apaga no máximo isto por execução, em GB "
                              "(default: sem teto).")
    lparser.add_argument("--dry-run", action="store_true",
                         help="só lista o que seria apagado.")

    largs = lparser.parse_args(flst_argv)

    if largs.retain_days is None and largs.min_free_gb is None:
        lparser.error("informe --retain-days, --min-free-gb ou os dois")

    if largs.retain_days is not None and largs.retain_days <= 0:
        lparser.error("--retain-days precisa ser > 0")

    if largs.max_days is not None:
        if largs.retain_days is None:
            lparser.error("--max-days exige --retain-days")

        if largs.max_days < largs.retain_days:
            lparser.error("--max-days precisa ser >= --retain-days")

    if largs.min_free_gb is not None and largs.min_free_gb <= 0:
        lparser.error("--min-free-gb precisa ser > 0")

    if largs.disk_min_age_hours < 0:
        lparser.error("--disk-min-age-hours precisa ser >= 0")

    if largs.disk_max_gb is not None:
        if largs.min_free_gb is None:
            lparser.error("--disk-max-gb exige --min-free-gb")

        if largs.disk_max_gb <= 0:
            lparser.error("--disk-max-gb precisa ser > 0")

    # ok
    return largs

# ─────────────────────────────────────────────────────────────────────────────────────
def _is_inside_sync_dir(fpth_file: pathlib.Path, fpth_sync_dir: pathlib.Path) -> bool:
    """
    confere se o arquivo está dentro do sync-dir

    os diretórios são resolvidos (symlinks seguidos), mas o arquivo não: um
    .mvol que seja ele próprio um symlink é julgado pelo lugar onde está, e
    não pelo destino

    :param fpth_file: .mvol candidato
    :param fpth_sync_dir: raiz permitida

    :returns: True se fpth_file está sob fpth_sync_dir
    """
    lpth_resolved_file = fpth_file.absolute().parent.resolve() / fpth_file.name

    try:
        lpth_resolved_file.relative_to(fpth_sync_dir.resolve())

    # relative_to falha quando o arquivo está fora da raiz
    except ValueError:
        # ok
        return False

    # ok
    return True

# ─────────────────────────────────────────────────────────────────────────────────────
def _check_sync_dir(fpth_sync_dir: pathlib.Path) -> None:
    """
    trava de segurança: recusa um sync-dir inexistente ou vazio.  um ponto
    de montagem desmontado aparece como diretório vazio, e todo .mvol
    pareceria ausente

    :raises RuntimeError: sync-dir inexistente ou vazio
    """
    if not fpth_sync_dir.is_dir():
        # raise an exception
        raise RuntimeError(f"sync-dir não é um diretório: {fpth_sync_dir}")

    lb_is_empty = next(fpth_sync_dir.iterdir(), None) is None

    if lb_is_empty:
        # raise an exception
        raise RuntimeError(f"sync-dir vazio (desmontado?): {fpth_sync_dir}")

# ─────────────────────────────────────────────────────────────────────────────────────
def _compute_cutoffs(fi_now: int, ff_retain_days: float,
                     ff_max_days: float | None) -> tuple:
    """
    converte as idades em dias em instantes de corte (epoch UTC)

    :param fi_now: instante de referência (epoch UTC)
    :param ff_retain_days: idade mínima para apagar um volume já convertido
    :param ff_max_days: idade a partir da qual um pendente também é apagado
                        (None = nunca)

    :returns: (corte de retenção, corte forçado ou None)
    """
    li_retain_cutoff = fi_now - int(ff_retain_days * MI_DAY_S)

    if ff_max_days is None:
        # ok
        return li_retain_cutoff, None

    li_forced_cutoff = fi_now - int(ff_max_days * MI_DAY_S)

    # ok
    return li_retain_cutoff, li_forced_cutoff

# ─────────────────────────────────────────────────────────────────────────────────────
def _purge_one_file(fdct_candidate: dict, fpth_sync_dir: pathlib.Path, fb_dry_run: bool,
                    fctr_summary: collections.Counter, fs_counter: str = CS_REMOVED) -> bool:
    """
    aplica a retenção a um candidato (apaga o .mvol, ou só simula)

    :param fdct_candidate: linha de vol_dbase.purge_candidates()
    :param fpth_sync_dir: raiz permitida
    :param fb_dry_run: True = só loga o que seria apagado
    :param fctr_summary: contadores CS_*, atualizados aqui
    :param fs_counter: contador de um .mvol apagado (CS_REMOVED pela idade,
                       CS_DISK pela guarda de disco)

    :returns: True se o volume deve ser marcado has_mvol=0 no banco (o
              arquivo foi apagado, seria apagado, ou já não existia)
    """
    lpth_file = pathlib.Path(fdct_candidate["fullpath"])

    # nunca apaga fora do sync-dir
    if not _is_inside_sync_dir(lpth_file, fpth_sync_dir):
        # logger
        M_LOG.warning("fora do sync-dir, não apagado: %s", lpth_file)
        fctr_summary[CS_OUTSIDE] += 1
        # não marca
        return False

    # pendente só chega aqui depois de --max-days, ou pela guarda de disco:
    # apaga, mas avisa
    if fdct_candidate["pending"]:
        # logger
        M_LOG.warning("%s ainda pendente, apagado pelo limite de %s", lpth_file.name,
                      "espaço livre" if CS_DISK == fs_counter else "idade (--max-days)")
        fctr_summary[CS_FORCED] += 1

    # arquivo já não existe: só corrige o banco -- se o diretório dele
    # existir.  a retenção nunca apaga diretórios, então diretório ausente é
    # montagem parcial/estação desmontada (o teste de sync-dir vazio só pega
    # a raiz): não marca, ou has_mvol=0 ficaria errado quando ele voltar
    if not lpth_file.exists():
        if not lpth_file.parent.is_dir():
            # logger
            M_LOG.warning("diretório ausente, has_mvol mantido: %s", lpth_file.parent)
            fctr_summary[CS_NO_DIR] += 1
            # não marca
            return False

        fctr_summary[CS_MISSING] += 1
        # marca
        return True

    if fb_dry_run:
        # logger
        M_LOG.info("apagaria %s", lpth_file)
        fctr_summary[fs_counter] += 1
        # "marca" (dry-run não grava no banco, ver purge)
        return True

    try:
        lpth_file.unlink()

    # em caso de erro,...
    except OSError as lerr:
        # logger
        M_LOG.error("não foi possível apagar %s: %s", lpth_file, lerr)
        fctr_summary[CS_ERROR] += 1
        # arquivo continua lá: não marca
        return False

    fctr_summary[fs_counter] += 1

    # marca
    return True

# ─────────────────────────────────────────────────────────────────────────────────────
def _mark_removed_in_dbase(fs_dbase_path: str, flst_volume_keys: list) -> None:
    """
    grava has_mvol=0 para os volumes cujo .mvol foi apagado, numa única
    transação de escrita

    :param flst_volume_keys: lista de (radar, alcance, timestamp)
    """
    if not flst_volume_keys:
        # nada a gravar
        return

    with vd.transaction_write(fs_dbase_path) as ldb:
        for ls_radar, li_alcance, li_timestamp in flst_volume_keys:
            ldb.mark_mvol_removed(ls_radar, li_alcance, li_timestamp)

# ─────────────────────────────────────────────────────────────────────────────────────
def _log_summary(fctr_summary: collections.Counter, fb_dry_run: bool) -> None:
    """
    loga uma linha com todos os contadores, na ordem de MT_SUMMARY_ORDER
    """
    llst_parts = []

    for ls_counter in MT_SUMMARY_ORDER:
        llst_parts.append(f"{ls_counter}: {fctr_summary[ls_counter]}")

    ls_prefix = ""

    if fb_dry_run:
        ls_prefix = "(dry-run) "

    # logger
    M_LOG.info("%s%s", ls_prefix, "  ".join(llst_parts))

# ─────────────────────────────────────────────────────────────────────────────────────
def _volume_key(fdct_candidate: dict) -> tuple:
    """
    chave única do volume: (radar, alcance, timestamp)
    """
    return fdct_candidate["radar"], fdct_candidate["alcance"], fdct_candidate["timestamp"]

# ─────────────────────────────────────────────────────────────────────────────────────
def _retain_by_age(fs_dbase_path: str, fpth_sync_dir: pathlib.Path, fi_now: int,
                   ff_retain_days: float, ff_max_days: float | None, fb_dry_run: bool,
                   fctr_summary: collections.Counter) -> list:
    """
    retenção por idade: apaga os .mvol de purge_candidates()

    :returns: chaves dos volumes a marcar has_mvol=0
    """
    li_retain_cutoff, li_forced_cutoff = _compute_cutoffs(fi_now, ff_retain_days, ff_max_days)

    with vd.transaction(fs_dbase_path) as ldb:
        llst_candidates = ldb.purge_candidates(li_retain_cutoff, li_forced_cutoff)

    ls_max_days_label = "nenhum"

    if ff_max_days is not None:
        ls_max_days_label = f"{ff_max_days:g} d"

    # logger
    M_LOG.info("candidatos: %d (retenção %g d, limite %s)", len(llst_candidates),
               ff_retain_days, ls_max_days_label)

    llst_volume_keys = []

    for ldct_candidate in llst_candidates:
        if _purge_one_file(ldct_candidate, fpth_sync_dir, fb_dry_run, fctr_summary):
            llst_volume_keys.append(_volume_key(ldct_candidate))

    # ok
    return llst_volume_keys

# ─────────────────────────────────────────────────────────────────────────────────────
def _free_bytes(fpth_dir: pathlib.Path) -> int:
    """
    bytes livres no sistema de arquivos de fpth_dir (para um usuário comum,
    como o df)
    """
    return shutil.disk_usage(fpth_dir).free

# ─────────────────────────────────────────────────────────────────────────────────────
def _disk_guard(fs_dbase_path: str, fpth_sync_dir: pathlib.Path, fi_min_free: int,
                fb_dry_run: bool, fctr_summary: collections.Counter, fn_free_bytes,
                fset_done: set, fi_newest_ts: int, fi_max_bytes: int | None) -> list:
    """
    guarda de disco: com menos de fi_min_free bytes livres, apaga os .mvol na
    ordem de vol_dbase.disk_candidates() (não pendentes antes, mais antigos
    antes, nunca PROCESSING) até voltar ao mínimo.  O espaço é medido de novo
    depois de cada remoção (no dry-run, estimado pelo tamanho do arquivo).
    Se acabarem os candidatos antes: [error] e contador CS_DISK_SHORT

    :param fset_done: chaves já apagadas pela retenção por idade nesta execução
    :param fi_newest_ts: piso de idade -- volumes com timestamp acima deste
                         epoch nunca saem por aqui
    :param fi_max_bytes: teto de bytes apagados nesta execução (None = sem
                         teto); atingido, para e conta CS_DISK_CAP

    :returns: chaves dos volumes a marcar has_mvol=0
    """
    li_free = fn_free_bytes(fpth_sync_dir)

    if li_free >= fi_min_free:
        # ok
        return []

    # logger
    M_LOG.warning("espaço livre %.2f GB < mínimo %.2f GB em %s: apagando os .mvol mais antigos",
                  li_free / MI_GB, fi_min_free / MI_GB, fpth_sync_dir)

    with vd.transaction(fs_dbase_path) as ldb:
        llst_candidates = ldb.disk_candidates()

    llst_volume_keys = []

    # bytes apagados nesta execução (para o teto)
    li_removed_bytes = 0

    for ldct_candidate in llst_candidates:
        if li_free >= fi_min_free:
            break

        # piso de idade: os mais novos ficam, mesmo pendentes (a lista está
        # ordenada por pendente e só depois por horário: continue, não break)
        if ldct_candidate["timestamp"] > fi_newest_ts:
            # next
            continue

        lt_key = _volume_key(ldct_candidate)

        if lt_key in fset_done:
            # next
            continue

        try:
            li_size = pathlib.Path(ldct_candidate["fullpath"]).stat().st_size

        # ausente: _purge_one_file só corrige o banco
        except OSError:
            li_size = 0

        # teto por execução: parar com o disco abaixo do mínimo é melhor do que
        # consumir o acervo inteiro numa rodada só -- o rc 1 chega ao monitor
        if fi_max_bytes is not None and li_removed_bytes + li_size > fi_max_bytes:
            # logger
            M_LOG.error("teto da guarda de disco atingido: %.2f GB apagados nesta execução "
                        "(limite %.2f GB)", li_removed_bytes / MI_GB, fi_max_bytes / MI_GB)
            fctr_summary[CS_DISK_CAP] += 1
            break

        if not _purge_one_file(ldct_candidate, fpth_sync_dir, fb_dry_run, fctr_summary, CS_DISK):
            # next
            continue

        llst_volume_keys.append(lt_key)
        li_removed_bytes += li_size

        if fb_dry_run:
            li_free += li_size

        else:
            li_free = fn_free_bytes(fpth_sync_dir)

    if li_free < fi_min_free:
        # logger
        M_LOG.error("espaço livre ainda %.2f GB < mínimo %.2f GB em %s: nada mais a apagar "
                    "(PROCESSING, volumes abaixo do piso de idade, arquivos fora do "
                    "registro e o teto por execução não deixam)",
                    li_free / MI_GB, fi_min_free / MI_GB, fpth_sync_dir)
        fctr_summary[CS_DISK_SHORT] += 1

    # ok
    return llst_volume_keys

# ─────────────────────────────────────────────────────────────────────────────────────
def purge(fs_dbase_path: str, fpth_sync_dir: pathlib.Path, ff_retain_days: float | None,
          ff_max_days: float | None = None, fb_dry_run: bool = False,
          fi_now: int | None = None, ff_min_free_gb: float | None = None,
          fn_free_bytes=None, ff_disk_min_age_h: float = MF_DISK_MIN_AGE_H,
          ff_disk_max_gb: float | None = None) -> collections.Counter:
    """
    aplica a retenção.  fluxo:

    1. confere o sync-dir (_check_sync_dir);
    2. retenção por idade, se ff_retain_days (_retain_by_age): candidatos do
       banco (vol_dbase.purge_candidates), cada .mvol apagado
       (_purge_one_file) -- arquivo primeiro...
    3. guarda de disco, se ff_min_free_gb (_disk_guard): mais antigos até o
       espaço livre voltar ao mínimo, respeitando o piso de idade e o teto;
    4. ...banco depois (_mark_removed_in_dbase): se a gravação falhar, a
       próxima execução acha o arquivo ausente e corrige has_mvol.

    :param fs_dbase_path: caminho do catalog.db
    :param fpth_sync_dir: raiz dos .mvol; nada fora dela é apagado
    :param ff_retain_days: idade mínima (dias) para apagar (None = sem
                           retenção por idade)
    :param ff_max_days: idade (dias) a partir da qual um pendente também é
                        apagado (None = nunca)
    :param fb_dry_run: True = só lista, não apaga nem grava
    :param fi_now: instante de referência (epoch UTC); None = agora (testes)
    :param ff_min_free_gb: espaço livre mínimo (GB) no sistema de arquivos do
                           sync-dir (None = sem guarda de disco)
    :param fn_free_bytes: função(pathlib.Path) -> bytes livres; None = o do
                          sistema de arquivos (testes injetam outra)
    :param ff_disk_min_age_h: piso de idade da guarda de disco, em horas
    :param ff_disk_max_gb: teto de GB apagados pela guarda nesta execução
                           (None = sem teto)

    :raises RuntimeError: --sync-dir inexistente ou vazio
    :raises sqlite3.Error: falha de banco

    :returns: contadores (CS_*)
    """
    # logger
    M_LOG.debug(">> purge")

    _check_sync_dir(fpth_sync_dir)

    lctr_summary = collections.Counter()

    # volumes cujo has_mvol vai a 0: (radar, alcance, timestamp)
    llst_volume_keys = []

    li_now = fi_now

    if li_now is None:
        li_now = int(time.time())

    if ff_retain_days is not None:
        llst_volume_keys += _retain_by_age(fs_dbase_path, fpth_sync_dir, li_now, ff_retain_days,
                                           ff_max_days, fb_dry_run, lctr_summary)

    if ff_min_free_gb is not None:
        if fn_free_bytes is None:
            fn_free_bytes = _free_bytes

        li_max_bytes = None

        if ff_disk_max_gb is not None:
            li_max_bytes = int(ff_disk_max_gb * MI_GB)

        llst_volume_keys += _disk_guard(fs_dbase_path, fpth_sync_dir,
                                        int(ff_min_free_gb * MI_GB), fb_dry_run, lctr_summary,
                                        fn_free_bytes, set(llst_volume_keys),
                                        li_now - int(ff_disk_min_age_h * MI_HOUR_S),
                                        li_max_bytes)

    # dry-run nunca grava no banco
    if not fb_dry_run:
        _mark_removed_in_dbase(fs_dbase_path, llst_volume_keys)

    _log_summary(lctr_summary, fb_dry_run)

    # ok
    return lctr_summary

# ─────────────────────────────────────────────────────────────────────────────────────
def main(flst_argv: list | None = None) -> int:
    """
    drive app

    :returns: 0 em sucesso, 1 em erro (banco, sync-dir, algum .mvol que não
              pôde ser apagado, ou espaço livre ainda abaixo de --min-free-gb
              -- inclusive quando o piso de idade ou o teto impediram)
    """
    # logger
    M_LOG.debug(">> main")

    # parse args
    largs = arg_parse(flst_argv)

    try:
        lctr = purge(largs.dbase, largs.sync_dir, largs.retain_days, largs.max_days,
                     largs.dry_run, ff_min_free_gb=largs.min_free_gb,
                     ff_disk_min_age_h=largs.disk_min_age_hours,
                     ff_disk_max_gb=largs.disk_max_gb)

    # em caso de erro,...
    except (sqlite3.Error, RuntimeError) as lerr:
        # logger
        M_LOG.error("volPurge: %s", lerr)
        # quit fail
        return 1

    # algum .mvol não pôde ser apagado, ou o disco continua abaixo do mínimo ?
    if lctr[CS_ERROR] or lctr[CS_DISK_SHORT]:
        # quit fail
        return 1

    # ok
    return 0

# ─────────────────────────────────────────────────────────────────────────────────────
# this is the bootstrap process

if "__main__" == __name__:
    # logger (horários do log em UTC, como todo o resto do sistema)
    logging.Formatter.converter = time.gmtime
    logging.basicConfig(datefmt="%Y/%m/%d %H:%M:%S",
                        format="%(asctime)s %(levelname)s %(message)s",
                        level=logging.INFO)

    # run
    sys.exit(main())

# < the end >──────────────────────────────────────────────────────────────────────────
