# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

volScan
varre os diretórios de .mvol sincronizados (vol_sync.sh) e registra/atualiza
cada volume na tabela volumes do catalog.db compartilhado (vol_dbase).

fluxo (scan):
  1. lista os *.mvol de cada --raw-dir (list_mvol_files);
  2. fase de LEITURA: para cada arquivo, extrai radar/alcance/timestamp do
     nome e compara com o registro atual no banco para decidir a ação
     (inserir, atualizar, pular ou ignorar -- _decide_action);
  3. fase SEM TRANSAÇÃO: calcula o SHA1 só dos arquivos novos/alterados
     (é a parte lenta: lê o arquivo inteiro);
  4. fase de ESCRITA curta: reconfere a ação (o banco pode ter mudado desde
     a fase 2) e grava.

por que três fases: o catalog.db é compartilhado com o nwcConvert (nowcast),
que roda em paralelo.  Segurar o lock de escrita durante o SHA1 de muitos
arquivos fazia o nwcConvert morrer com "database is locked".

regras:
- o horário do nome é UTC; o timestamp gravado é o epoch desse instante;
- incremental: mesmo fullpath e mesmo filesize = nada mudou, pula sem SHA1;
- um segundo arquivo para um volume já registrado cujo arquivo ainda existe
  (ex.: cópia "(1)") é ignorado, em vez de alternar entre os dois.

uso:
    python volScan.py <catalog.db> --raw-dir <dir> [--raw-dir <dir>...] [--no-sha1]

2026.out  mlabru  refatoração para legibilidade: scan() dividido em uma
                  função por fase; ações como constantes CS_ACTION_*;
                  candidatos como CVolumeCandidate (sem tuplas posicionais)
2026.out  mlabru  scan() em três fases (leitura / SHA1 sem transação / escrita
                  curta): a varredura inteira, com o SHA1 de cada .mvol novo,
                  rodava dentro de um BEGIN IMMEDIATE e, após um sync grande,
                  segurava o lock por mais que o busy_timeout (10 s) do
                  nwcConvert, que roda em paralelo e morria com "database is
                  locked" no plan()
2026.set  mlabru  initial version (Linux/Python) -- lógica portada de
                  apps/work/nc_scan_mvol.py, com correções:
                  - timestamp em UTC (nc_scan_mvol fazia strptime naive +
                    .timestamp(), interpretando o horário UTC do nome como
                    hora local: +3h no Brasil)
                  - parser único do nome (rd_mvol.parse_mvol, aceita o
                    sufixo "(1)")
                  - varredura incremental (antes recalculava o SHA1 de
                    todos os arquivos a cada execução)
"""
# < imports >──────────────────────────────────────────────────────────────────────────

# python library
import argparse
import hashlib
import logging
import pathlib
import sqlite3
import sys
import time
import typing

# radar
import radar.rd_mvol as mv

# locals
import dbase.vol_dbase as vd

# < constants >────────────────────────────────────────────────────────────────────────

# bloco de leitura para o SHA1 (1 MB, evita carregar o arquivo inteiro)
MI_SHA1_BLOCK = 1024 * 1024

# ações possíveis para um arquivo encontrado (ver _decide_action)
CS_ACTION_INSERT = "insert"     # volume ainda não registrado
CS_ACTION_UPDATE = "update"     # volume registrado, arquivo mudou
CS_ACTION_SKIP = "skip"         # mesmo arquivo, mesmo tamanho: nada a fazer
CS_ACTION_IGNORE = "ignore"     # outra cópia de um volume já registrado

# < logging >──────────────────────────────────────────────────────────────────────────

# logger
M_LOG = logging.getLogger(__name__)
M_LOG.setLevel(logging.INFO)

# < CVolumeCandidate >─────────────────────────────────────────────────────────────────

class CVolumeCandidate(typing.NamedTuple):
    """
    um .mvol que precisa ser gravado (novo ou alterado)

    os três primeiros campos formam a chave única do volume na tabela
    volumes: (radar, alcance, timestamp)
    """
    # arquivo no disco
    file_path: pathlib.Path
    # sigla da estação (ex.: "CGU")
    radar: str
    # alcance em km (ex.: 250, 400)
    alcance: int
    # epoch UTC do horário do nome do arquivo
    timestamp: int
    # caminho absoluto resolvido, como é gravado no banco
    fullpath: str
    # tamanho em bytes
    filesize: int
    # SHA1 hexadecimal (preenchido na fase 2; None se --no-sha1)
    sha1: str | None = None

# ─────────────────────────────────────────────────────────────────────────────────────
def arg_parse():
    """
    lê os argumentos da linha de comando

    :returns: argparse.Namespace com dbase, raw_dirs e sha1
    """
    # logger
    M_LOG.debug(">> arg_parse")

    # create parser
    lparser = argparse.ArgumentParser(
                 description="Registra os .mvol encontrados na tabela volumes do catalog.db.")

    # caminho do catalog.db compartilhado
    lparser.add_argument("dbase", type=str, help="caminho do catalog.db compartilhado.")

    # diretórios a varrer
    lparser.add_argument("-r", "--raw-dir", dest="raw_dirs", action="append", required=True,
                         type=pathlib.Path, help="diretório com .mvol (repetível).")

    # SHA1
    lparser.add_argument("--no-sha1", dest="sha1", action="store_false",
                         help="não calcula o SHA1 dos arquivos novos/alterados.")

    # ok
    return lparser.parse_args()

# -------------------------------------------------------------------------------------
def calculate_sha1(fpth_file: pathlib.Path) -> str:
    """
    calcula o SHA1 do arquivo, lendo em blocos de MI_SHA1_BLOCK bytes (não
    carrega o arquivo inteiro na memória)

    :param fpth_file: arquivo a ler

    :returns: digest hexadecimal
    """
    # logger
    M_LOG.debug(">> calculate_sha1")

    lsha1 = hashlib.sha1()

    with open(fpth_file, "rb") as lfh:
        while True:
            lblock = lfh.read(MI_SHA1_BLOCK)

            # fim do arquivo
            if not lblock:
                break

            lsha1.update(lblock)

    # ok
    return lsha1.hexdigest()

# -------------------------------------------------------------------------------------
def list_mvol_files(flst_dirs: list) -> list:
    """
    procura recursivamente os *.mvol em cada diretório existente, em ordem
    determinística.  os temporários do rsync (".<nome>.XXXXXX") não terminam
    em .mvol e ficam de fora

    :param flst_dirs: lista de pathlib.Path a varrer; diretório inexistente
                      só gera um aviso

    :returns: lista de pathlib.Path
    """
    # logger
    M_LOG.debug(">> list_mvol_files")

    llst_files = []

    # for all directories...
    for lpth_dir in flst_dirs:
        if not lpth_dir.is_dir():
            # logger
            M_LOG.warning("diretório inexistente, ignorado: %s", lpth_dir)
            # next
            continue

        # busca recursiva ordenada
        llst_dir_files = sorted(lpth_dir.rglob("*.mvol"))

        # logger
        M_LOG.info("arquivo(s) .mvol em %s: %d", lpth_dir, len(llst_dir_files))

        llst_files.extend(llst_dir_files)

    # ok
    return llst_files

# -------------------------------------------------------------------------------------
def _read_mvol_identity(fpth_file: pathlib.Path) -> CVolumeCandidate | None:
    """
    monta o candidato de um arquivo a partir do nome (radar, alcance,
    horário UTC) e do stat (tamanho)

    :param fpth_file: .mvol encontrado

    :returns: CVolumeCandidate (sem SHA1), ou None se o nome não seguir o
              padrão .mvol
    """
    try:
        l_mvol = mv.parse_mvol(fpth_file)

    # nome fora do padrão / alcance desconhecido
    except ValueError as lerr:
        # logger
        M_LOG.warning("nome fora do padrão, ignorado: %s (%s)", fpth_file.name, lerr)
        # sem candidato
        return None

    # ok
    return CVolumeCandidate(file_path=fpth_file,
                            radar=l_mvol.product.station,
                            alcance=l_mvol.product.range_km,
                            # epoch do instante UTC do nome do arquivo
                            timestamp=int(l_mvol.timestamp.timestamp()),
                            fullpath=str(fpth_file.resolve()),
                            filesize=fpth_file.stat().st_size)

# -------------------------------------------------------------------------------------
def _decide_action(frow, fs_fullpath: str, fi_filesize: int) -> str:
    """
    decide o que fazer com um arquivo, dado o registro atual do volume

    :param frow: registro atual do volume (sqlite3.Row) ou None se o volume
                 ainda não estiver registrado
    :param fs_fullpath: caminho absoluto do arquivo encontrado
    :param fi_filesize: tamanho do arquivo encontrado

    :returns: uma das constantes CS_ACTION_*
    """
    # volume novo
    if frow is None:
        return CS_ACTION_INSERT

    lb_same_file = frow["fullpath"] == fs_fullpath

    # mesmo arquivo, mesmo tamanho: nada mudou
    if lb_same_file and frow["filesize"] == fi_filesize:
        return CS_ACTION_SKIP

    # outro arquivo, ainda presente, para o mesmo volume (ex: cópia "(1)" ou o
    # mesmo .mvol em outro diretório): mantém o registrado, em vez de alternar
    # entre os dois a cada varredura
    if not lb_same_file and pathlib.Path(frow["fullpath"]).exists():
        return CS_ACTION_IGNORE

    # volume conhecido: atualiza localização/integridade
    return CS_ACTION_UPDATE

# -------------------------------------------------------------------------------------
def _log_ignored_duplicate(fcandidate: CVolumeCandidate, fs_registered_path: str) -> None:
    """
    avisa que um arquivo foi ignorado porque o volume já está registrado com
    outro arquivo que ainda existe
    """
    # logger
    M_LOG.warning("volume %s %d %d já registrado com %s; ignorando %s",
                  fcandidate.radar, fcandidate.alcance, fcandidate.timestamp,
                  fs_registered_path, fcandidate.fullpath)

# -------------------------------------------------------------------------------------
def _collect_candidates(fs_dbase_path: str, flst_files: list, fdct_count: dict) -> list:
    """
    fase 1 (só leitura): decide, para cada arquivo, se ele precisa ser
    gravado.  arquivos pulados/ignorados só incrementam fdct_count

    :param fs_dbase_path: caminho do catalog.db
    :param flst_files: arquivos .mvol encontrados
    :param fdct_count: contadores, atualizados aqui

    :raises sqlite3.Error: falha de banco interrompe a varredura

    :returns: lista de CVolumeCandidate a gravar
    """
    # logger
    M_LOG.debug(">> _collect_candidates")

    llst_candidates = []

    # transação de leitura (WAL: não bloqueia escritores)
    with vd.transaction(fs_dbase_path) as ldb:
        for lpth_file in flst_files:
            try:
                lcandidate = _read_mvol_identity(lpth_file)

            # erro inesperado num arquivo específico (ex.: sumiu no meio da
            # varredura): loga e segue.  o banco não é acessado dentro deste
            # try, então um erro de banco nunca é engolido aqui
            except Exception as lerr:
                # logger
                M_LOG.exception("erro processando %s: %s", lpth_file.name, lerr)
                fdct_count["ignored"] += 1
                # next
                continue

            # nome inválido (já avisado)
            if lcandidate is None:
                fdct_count["ignored"] += 1
                # next
                continue

            # volume já registrado ?
            lrow = ldb.get_volume(lcandidate.radar, lcandidate.alcance, lcandidate.timestamp)

            ls_action = _decide_action(lrow, lcandidate.fullpath, lcandidate.filesize)

            if CS_ACTION_SKIP == ls_action:
                fdct_count["skipped"] += 1
                # next
                continue

            if CS_ACTION_IGNORE == ls_action:
                _log_ignored_duplicate(lcandidate, lrow["fullpath"])
                fdct_count["ignored"] += 1
                # next
                continue

            llst_candidates.append(lcandidate)

    # ok
    return llst_candidates

# -------------------------------------------------------------------------------------
def _compute_sha1_for_candidates(flst_candidates: list, fb_sha1: bool,
                                 fdct_count: dict) -> list:
    """
    fase 2 (fora de qualquer transação): calcula o SHA1 de cada candidato.
    um arquivo que não puder ser lido sai da lista (conta como ignorado)

    :param flst_candidates: lista de CVolumeCandidate
    :param fb_sha1: False = não calcula (sha1 fica None)
    :param fdct_count: contadores, atualizados aqui

    :returns: lista de CVolumeCandidate com sha1 preenchido
    """
    # logger
    M_LOG.debug(">> _compute_sha1_for_candidates")

    # sem SHA1: os candidatos seguem como estão (sha1=None)
    if not fb_sha1:
        return list(flst_candidates)

    llst_ready = []

    for lcandidate in flst_candidates:
        try:
            ls_sha1 = calculate_sha1(lcandidate.file_path)

        # erro ao ler este arquivo: loga e segue com os demais
        except Exception as lerr:
            # logger
            M_LOG.exception("erro processando %s: %s", lcandidate.file_path.name, lerr)
            fdct_count["ignored"] += 1
            # next
            continue

        llst_ready.append(lcandidate._replace(sha1=ls_sha1))

    # ok
    return llst_ready

# -------------------------------------------------------------------------------------
def _write_candidates(fs_dbase_path: str, flst_candidates: list, fdct_count: dict) -> None:
    """
    fase 3 (transação de escrita curta): reconfere cada candidato e grava.
    a reconferência é necessária porque o registro pode ter mudado desde a
    fase 1, ou outra cópia do mesmo volume pode ter sido gravada agora

    um erro de banco desfaz a transação inteira (nada é gravado)

    :param fs_dbase_path: caminho do catalog.db
    :param flst_candidates: lista de CVolumeCandidate (com SHA1)
    :param fdct_count: contadores, atualizados aqui

    :raises sqlite3.Error: falha de banco
    """
    # logger
    M_LOG.debug(">> _write_candidates")

    with vd.transaction_write(fs_dbase_path) as ldb:
        for lcandidate in flst_candidates:
            lrow = ldb.get_volume(lcandidate.radar, lcandidate.alcance, lcandidate.timestamp)

            ls_action = _decide_action(lrow, lcandidate.fullpath, lcandidate.filesize)

            if CS_ACTION_SKIP == ls_action:
                fdct_count["skipped"] += 1
                # next
                continue

            if CS_ACTION_IGNORE == ls_action:
                _log_ignored_duplicate(lcandidate, lrow["fullpath"])
                fdct_count["ignored"] += 1
                # next
                continue

            if CS_ACTION_INSERT == ls_action:
                ldb.insert_volume(lcandidate.radar, lcandidate.alcance, lcandidate.timestamp,
                                  lcandidate.fullpath, lcandidate.filesize, lcandidate.sha1)
                # logger
                M_LOG.info("novo volume: %s %d %d",
                           lcandidate.radar, lcandidate.alcance, lcandidate.timestamp)
                fdct_count["inserted"] += 1
                # next
                continue

            # CS_ACTION_UPDATE
            ldb.update_volume(lcandidate.radar, lcandidate.alcance, lcandidate.timestamp,
                              lcandidate.fullpath, lcandidate.filesize, lcandidate.sha1)
            fdct_count["updated"] += 1

# -------------------------------------------------------------------------------------
def scan(fs_dbase_path: str, flst_dirs: list, fb_sha1: bool = True) -> dict:
    """
    registra/atualiza na tabela volumes os .mvol encontrados (ver o fluxo
    em três fases na docstring do módulo)

    :param fs_dbase_path: caminho do catalog.db
    :param flst_dirs: diretórios a varrer (pathlib.Path)
    :param fb_sha1: calcula o SHA1 de volumes novos/alterados

    :raises sqlite3.Error: falha de banco (nada da fase 3 é gravado)

    :returns: contadores {"inserted", "updated", "skipped", "ignored"}
    """
    # logger
    M_LOG.debug(">> scan")

    ldct_count = {"inserted": 0, "updated": 0, "skipped": 0, "ignored": 0}

    llst_files = list_mvol_files(flst_dirs)

    # logger
    M_LOG.info("total de arquivos encontrados: %d", len(llst_files))

    # 1. leitura: o que é novo/alterado
    llst_candidates = _collect_candidates(fs_dbase_path, llst_files, ldct_count)

    # 2. SHA1, sem segurar lock nenhum
    llst_candidates = _compute_sha1_for_candidates(llst_candidates, fb_sha1, ldct_count)

    # 3. escrita curta
    _write_candidates(fs_dbase_path, llst_candidates, ldct_count)

    # logger
    M_LOG.info("inseridos: %(inserted)d  atualizados: %(updated)d  "
               "pulados: %(skipped)d  ignorados: %(ignored)d", ldct_count)

    # ok
    return ldct_count

# ─────────────────────────────────────────────────────────────────────────────────────
def main() -> int:
    """
    drive app

    :returns: 0 em sucesso, 1 se a gravação no catalog.db falhar
    """
    # logger
    M_LOG.debug(">> main")

    # parse args
    largs = arg_parse()

    try:
        # varre e registra
        scan(largs.dbase, largs.raw_dirs, largs.sha1)

    # em caso de erro de banco,...
    except sqlite3.Error as lerr:
        # logger
        M_LOG.error("falha no catalog.db (%s): %s", largs.dbase, lerr)
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
    # módulos importados (rd_mvol, vol_product_key...) fixam o próprio logger
    # em DEBUG; limita o handler a INFO para não logar um trace por arquivo
    logging.root.handlers[0].setLevel(logging.INFO)

    # run
    sys.exit(main())

# < the end >──────────────────────────────────────────────────────────────────────────
