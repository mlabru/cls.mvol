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

- arquivo que já não existe: só corrige has_mvol=0

- apaga primeiro e grava o banco depois, numa transação: se a gravação
  falhar, o próximo run acha o arquivo ausente e corrige has_mvol

- sintéticos (status 4/5) e volumes não registrados não são tocados

uso:
    python volPurge.py <catalog.db> --sync-dir <dir> --retain-days N
                       [--max-days M] [--dry-run]

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
import sqlite3
import sys
import time

# locals
import dbase.vol_dbase as vd

# < constants >────────────────────────────────────────────────────────────────────────

# segundos por dia
MI_DAY_S = 86400

# contadores do resumo
CS_REMOVED = "removidos"
CS_MISSING = "ausentes"
CS_FORCED = "forçados"
CS_OUTSIDE = "fora do sync-dir"
CS_ERROR = "erros"

# ordem dos contadores na linha de resumo do log
MT_SUMMARY_ORDER = (CS_REMOVED, CS_MISSING, CS_FORCED, CS_OUTSIDE, CS_ERROR)

# < logging >──────────────────────────────────────────────────────────────────────────

# logger
M_LOG = logging.getLogger(__name__)
M_LOG.setLevel(logging.INFO)

# ─────────────────────────────────────────────────────────────────────────────────────
def arg_parse(flst_argv: list | None = None):
    """
    lê e valida os argumentos da linha de comando

    :param flst_argv: argumentos (None = sys.argv; testes passam uma lista)

    :returns: argparse.Namespace com dbase, sync_dir, retain_days, max_days
              e dry_run
    """
    # logger
    M_LOG.debug(">> arg_parse")

    # create parser
    lparser = argparse.ArgumentParser(
                 description="Apaga os .mvol antigos já convertidos (retenção).")

    lparser.add_argument("dbase", type=str, help="caminho do catalog.db compartilhado.")
    lparser.add_argument("--sync-dir", required=True, type=pathlib.Path,
                         help="raiz dos .mvol sincronizados; nada fora dela é apagado.")
    lparser.add_argument("--retain-days", required=True, type=float,
                         help="idade mínima (dias, pelo horário do volume) para apagar.")
    lparser.add_argument("--max-days", type=float, default=None,
                         help="idade a partir da qual um pendente também é apagado "
                              "(default: nunca).")
    lparser.add_argument("--dry-run", action="store_true",
                         help="só lista o que seria apagado.")

    largs = lparser.parse_args(flst_argv)

    if largs.retain_days <= 0:
        lparser.error("--retain-days precisa ser > 0")

    if largs.max_days is not None and largs.max_days < largs.retain_days:
        lparser.error("--max-days precisa ser >= --retain-days")

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
                    fctr_summary: collections.Counter) -> bool:
    """
    aplica a retenção a um candidato (apaga o .mvol, ou só simula)

    :param fdct_candidate: linha de vol_dbase.purge_candidates()
    :param fpth_sync_dir: raiz permitida
    :param fb_dry_run: True = só loga o que seria apagado
    :param fctr_summary: contadores CS_*, atualizados aqui

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

    # pendente só chega aqui depois de --max-days: apaga, mas avisa
    if fdct_candidate["pending"]:
        # logger
        M_LOG.warning("%s ainda pendente, apagado pelo limite de disco", lpth_file.name)
        fctr_summary[CS_FORCED] += 1

    # arquivo já não existe: só corrige o banco
    if not lpth_file.exists():
        fctr_summary[CS_MISSING] += 1
        # marca
        return True

    if fb_dry_run:
        # logger
        M_LOG.info("apagaria %s", lpth_file)
        fctr_summary[CS_REMOVED] += 1
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

    fctr_summary[CS_REMOVED] += 1

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
def purge(fs_dbase_path: str, fpth_sync_dir: pathlib.Path, ff_retain_days: float,
          ff_max_days: float | None = None, fb_dry_run: bool = False,
          fi_now: int | None = None) -> collections.Counter:
    """
    aplica a retenção.  fluxo:

    1. confere o sync-dir (_check_sync_dir);
    2. calcula os cortes de idade (_compute_cutoffs);
    3. lê os candidatos do banco (vol_dbase.purge_candidates);
    4. apaga cada .mvol (_purge_one_file) -- arquivo primeiro...
    5. ...banco depois (_mark_removed_in_dbase): se a gravação falhar, a
       próxima execução acha o arquivo ausente e corrige has_mvol.

    :param fs_dbase_path: caminho do catalog.db
    :param fpth_sync_dir: raiz dos .mvol; nada fora dela é apagado
    :param ff_retain_days: idade mínima (dias) para apagar
    :param ff_max_days: idade (dias) a partir da qual um pendente também é
                        apagado (None = nunca)
    :param fb_dry_run: True = só lista, não apaga nem grava
    :param fi_now: instante de referência (epoch UTC); None = agora (testes)

    :raises RuntimeError: --sync-dir inexistente ou vazio
    :raises sqlite3.Error: falha de banco

    :returns: contadores (CS_*)
    """
    # logger
    M_LOG.debug(">> purge")

    _check_sync_dir(fpth_sync_dir)

    li_now = fi_now

    if li_now is None:
        li_now = int(time.time())

    li_retain_cutoff, li_forced_cutoff = _compute_cutoffs(li_now, ff_retain_days, ff_max_days)

    with vd.transaction(fs_dbase_path) as ldb:
        llst_candidates = ldb.purge_candidates(li_retain_cutoff, li_forced_cutoff)

    ls_max_days_label = "nenhum"

    if ff_max_days is not None:
        ls_max_days_label = f"{ff_max_days:g} d"

    # logger
    M_LOG.info("candidatos: %d (retenção %g d, limite %s)", len(llst_candidates),
               ff_retain_days, ls_max_days_label)

    lctr_summary = collections.Counter()

    # volumes cujo has_mvol vai a 0: (radar, alcance, timestamp)
    llst_volume_keys = []

    for ldct_candidate in llst_candidates:
        lb_mark = _purge_one_file(ldct_candidate, fpth_sync_dir, fb_dry_run, lctr_summary)

        if lb_mark:
            llst_volume_keys.append((ldct_candidate["radar"], ldct_candidate["alcance"],
                                     ldct_candidate["timestamp"]))

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

    :returns: 0 em sucesso, 1 em erro (banco, sync-dir, ou algum .mvol que não
              pôde ser apagado)
    """
    # logger
    M_LOG.debug(">> main")

    # parse args
    largs = arg_parse(flst_argv)

    try:
        lctr = purge(largs.dbase, largs.sync_dir, largs.retain_days, largs.max_days,
                     largs.dry_run)

    # em caso de erro,...
    except (sqlite3.Error, RuntimeError) as lerr:
        # logger
        M_LOG.error("volPurge: %s", lerr)
        # quit fail
        return 1

    # algum .mvol não pôde ser apagado ?
    if lctr[CS_ERROR]:
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
