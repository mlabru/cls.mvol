# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

volDBWriter
grava no catalog.db compartilhado as observações brutas dos .mvol vistos
pela listagem remota de vol_sync.sh, antes do rsync -- como vol_sync.sh
sempre remove do servidor o que baixou, esta tabela é o único histórico de
recepção desses arquivos.

grava, por arquivo:
- fullpath: caminho relativo a REMOTE_DIR, como vem da listagem (find
  -printf '%P'); caminho absoluto aborta a gravação (vol_catalog.check_relpath);
- timestamp: epoch UTC extraído do nome (rd_mvol.parse_mvol) -- o tempo
  confiável do volume, mesmo conteúdo de volumes.timestamp;
- mtime: hora de chegada pelo relógio do servidor (find %T@) -- bruta, pode
  estar errada se o servidor estiver fora de hora.

a DDL vive só em cls_common.dbase.schema (migrações 1 e 2).

modos:
- padrão: grava a listagem (stdin "mtime|caminho"); um nome já recebido que
  reaparece é um reenvio (resends + 1, received_at volta a NULL);
- --received --sync-dir D: marca received_at dos caminhos da stdin (a lista
  de transferência) que existem em D -- chamado pelo vol_sync.sh depois do
  rsync.

2026.nov  mlabru  histórico de recepção (migração 2): reenvios contados
                  (resends, last_mtime) e modo --received (received_at)
2026.nov  mlabru  imports cls_common.* (pacote do repo cls.common, via
                  CLS_PYLIB; antes symlinks de diretório)
2026.nov  mlabru  confere a versão do esquema (cls_common.dbase.schema) em vez
                  de criar/migrar a tabela (vol_catalog.ensure_schema saiu):
                  banco não migrado = rc 1, e vol_sync.sh não baixa nada
2026.nov  mlabru  log em UTC (era hora local, contra o contrato "tudo é
                  UTC"); loga quantas observações eram novas
2026.out  mlabru  refatoração para legibilidade: parse_lines() usa
                  _parse_one_line() (guard clauses); write_observations()
                  monta os parâmetros em variáveis nomeadas; removido código
                  comentado do bootstrap

2026.set  mlabru  - fullpath relativo a REMOTE_DIR: listagem com caminho
                    absoluto faz main() retornar 1 (vol_sync.sh então não
                    baixa nem remove nada)
                  - coluna obs_time renomeada para timestamp (inteiro),
                    mesmo nome de volumes.timestamp; obs_time() ->
                    name_timestamp();
                  - grava obs_time (tempo do nome, UTC) além do mtime; migra
                    bases antigas (vol_catalog.ensure_schema) e preenche o
                    obs_time de linhas já gravadas sem ele;
                  - fix: CS_SOURCE é local (não existe em vol_catalog)

2026.ago  mlabru  initial version (Linux/Python)
"""
# < imports >──────────────────────────────────────────────────────────────────────────

# python library
import argparse
import datetime
import logging
import pathlib
import sqlite3
import sys
import time

# locals
import cls_common.radar.rd_mvol as mv
import cls_common.dbase.schema as sc
import cls_common.dbase.vol_catalog as ct

# < constants >────────────────────────────────────────────────────────────────────────

# origem gravada na coluna "source"
CS_SOURCE = "mvol"

# < logging >──────────────────────────────────────────────────────────────────────────

# logger
M_LOG = logging.getLogger(__name__)
M_LOG.setLevel(logging.INFO)

# ─────────────────────────────────────────────────────────────────────────────────────
def arg_parse():
    """
    lê os argumentos da linha de comando (as linhas vêm da stdin)

    :returns: argparse.Namespace com dbase, received e sync_dir
    """
    # logger
    M_LOG.debug(">> arg_parse")

    # create parser
    lparser = argparse.ArgumentParser(
                 description="Grava no catalog.db as observações "
                             "de arquivos radar lidas da stdin "
                             "(mtime|caminho relativo a REMOTE_DIR).")

    # caminho do catalog.db compartilhado
    lparser.add_argument("dbase", help="caminho do catalog.db compartilhado.",
                                  type=str)

    # modo recepção: a stdin é a lista de transferência (um caminho por linha)
    lparser.add_argument("--received", action="store_true",
                         help="marca como recebidos (received_at) os caminhos da stdin "
                              "que existem em --sync-dir.")
    lparser.add_argument("--sync-dir", type=pathlib.Path, default=None,
                         help="destino do rsync (VOL_SYNC_DIR); exigido por --received.")

    largs = lparser.parse_args()

    if largs.received and largs.sync_dir is None:
        lparser.error("--received exige --sync-dir")

    # ok
    return largs

# ─────────────────────────────────────────────────────────────────────────────────────
def _parse_one_line(fs_line: str) -> tuple | None:
    """
    converte uma linha "mtime|caminho" em (fullpath, mtime, timestamp)

    :param fs_line: linha da listagem (pode ter espaços/quebra de linha)

    :raises ValueError: caminho absoluto (vol_catalog.check_relpath) -- não
                        descarta só a linha: a listagem inteira está fora do
                        contrato

    :returns: (fullpath, mtime, timestamp), ou None se a linha estiver vazia
              ou malformada (malformada gera um aviso)
    """
    ls_line = fs_line.strip()

    # linha vazia
    if not ls_line:
        return None

    # sem separador '|'
    if '|' not in ls_line:
        # logger
        M_LOG.warning("linha ignorada (sem separador '|'): %s", ls_line)
        # descarta
        return None

    # o caminho é tudo após o primeiro '|'
    ls_mtime, ls_filepath = ls_line.split('|', 1)

    try:
        lf_mtime = float(ls_mtime)

    # mtime não numérico
    except ValueError as lerr:
        # logger
        M_LOG.warning("linha ignorada (%s): %s", lerr, ls_line)
        # descarta
        return None

    # sem caminho
    if not ls_filepath:
        # logger
        M_LOG.warning("linha ignorada (caminho vazio): %s", ls_line)
        # descarta
        return None

    # caminho absoluto ? levanta ValueError (aborta a listagem toda)
    ct.check_relpath(ls_filepath)

    # ok
    return ls_filepath, lf_mtime, name_timestamp(ls_filepath)

# ─────────────────────────────────────────────────────────────────────────────────────
def parse_lines(flines) -> list:
    """
    converte linhas "mtime|caminho" (formato de list_remote_files() em
    vol_sync.sh, caminho relativo a REMOTE_DIR) em (fullpath, mtime,
    timestamp), descartando linhas vazias e malformadas.  timestamp é o
    epoch UTC do nome, ou None se o nome não seguir o padrão .mvol (a
    observação é gravada assim mesmo)

    :param flines: iterável de linhas (ex.: sys.stdin)

    :raises ValueError: linha com caminho absoluto -- listagem fora do
                        contrato, gravar misturaria formatos de fullpath

    :returns: lista de (fullpath, mtime, timestamp)
    """
    # logger
    M_LOG.debug(">> parse_lines")

    llst_rows = []

    for ls_line in flines:
        lt_row = _parse_one_line(ls_line)

        if lt_row is not None:
            llst_rows.append(lt_row)

    # ok
    return llst_rows

# ─────────────────────────────────────────────────────────────────────────────────────
def name_timestamp(fs_filepath: str) -> int | None:
    """
    epoch UTC do volume, extraído do nome do arquivo -- ao contrário do
    mtime, não depende do relógio do servidor

    :param fs_filepath: caminho (só o nome importa)

    :returns: epoch (int) ou None se o nome for inválido
    """
    try:
        l_mvol = mv.parse_mvol(fs_filepath)

    # nome fora do padrão / alcance desconhecido
    except ValueError as lerr:
        # logger
        M_LOG.warning("timestamp indisponível (%s): %s", lerr, fs_filepath)
        # sem tempo confiável
        return None

    # parse_mvol devolve datetime UTC-aware (o nome tem resolução de 1 s)
    return int(l_mvol.timestamp.timestamp())

# ─────────────────────────────────────────────────────────────────────────────────────
def write_observations(fs_dbase_path: str, flst_rows: list) -> int:
    """
    abre o catalog.db compartilhado (WAL, confere a versão do esquema) e grava as
    observações numa única transação:

    1. INSERT OR IGNORE: fullpath já gravado não é duplicado;
    2. UPDATE: linhas antigas gravadas sem timestamp ganham o do nome.

    :param fs_dbase_path: caminho do catalog.db
    :param flst_rows: lista de (fullpath, mtime, timestamp)

    :raises sqlite3.Error: falha de banco

    :returns: número de linhas novas
    """
    # logger
    M_LOG.debug(">> write_observations")

    # instante da gravação
    ls_now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # parâmetros do INSERT: (fullpath, mtime, timestamp, source, created_at,
    # last_mtime)
    llst_insert_params = []

    for ls_fullpath, lf_mtime, li_timestamp in flst_rows:
        llst_insert_params.append((ls_fullpath, lf_mtime, li_timestamp, CS_SOURCE, ls_now,
                                   lf_mtime))

    # parâmetros do UPDATE de reenvio: (last_mtime, fullpath)
    llst_resend_params = [(lf_mtime, ls_fullpath) for ls_fullpath, lf_mtime, _ in flst_rows]

    # parâmetros do UPDATE: (timestamp, fullpath), só quando há timestamp
    llst_update_params = []

    for ls_fullpath, _, li_timestamp in flst_rows:
        if li_timestamp is not None:
            llst_update_params.append((li_timestamp, ls_fullpath))

    # timeout de espera por lock -- arquivo compartilhado com outros
    # programas: o nowcast grava nas tabelas dele e o monrad lê esta
    lconn = sqlite3.connect(fs_dbase_path, timeout=10)

    try:
        lconn.execute("PRAGMA journal_mode = WAL")

        # esquema na versão do código ?  (migração é no deploy, não aqui)
        sc.check_schema(lconn, fs_dbase_path)

        lcursor = lconn.executemany(
            f"INSERT OR IGNORE INTO {ct.CS_TABLE} "
            f"(fullpath, mtime, timestamp, source, created_at, last_mtime) "
            f"VALUES (?, ?, ?, ?, ?, ?)", llst_insert_params)

        li_new_rows = lcursor.rowcount

        # reenvio: o nome já tinha sido RECEBIDO e está de novo no servidor.
        # Conta, guarda o mtime novo e volta a "não recebido" até chegar.  Um
        # nome que só continua no servidor (rsync falhou) tem received_at
        # NULL e não conta
        lcursor = lconn.executemany(
            f"UPDATE {ct.CS_TABLE} SET resends = resends + 1, received_at = NULL, "
            f"last_mtime = ? WHERE fullpath = ? AND received_at IS NOT NULL",
            llst_resend_params)

        li_resends = lcursor.rowcount

        lconn.executemany(
            f"UPDATE {ct.CS_TABLE} SET timestamp = ? WHERE fullpath = ? AND timestamp IS NULL",
            llst_update_params)

        lconn.commit()

    finally:
        lconn.close()

    if li_resends:
        # logger
        M_LOG.warning("reenvios: %d arquivo(s) já recebidos reapareceram no servidor", li_resends)

    # ok
    return li_new_rows

# ─────────────────────────────────────────────────────────────────────────────────────
def mark_received(fs_dbase_path: str, flst_paths: list, fpth_sync_dir: pathlib.Path) -> tuple:
    """
    marca received_at nas observações cujos arquivos existem agora em
    fpth_sync_dir (o destino do rsync).  Conferir o disco, e não a saída do
    rsync, é o que vale: um arquivo já idêntico no destino não aparece como
    transferido, e numa falha parcial os que vieram ficam marcados

    :param fs_dbase_path: caminho do catalog.db
    :param flst_paths: caminhos relativos a REMOTE_DIR (= relativos ao sync-dir)
    :param fpth_sync_dir: VOL_SYNC_DIR

    :raises sqlite3.Error: falha de banco (inclusive esquema em outra versão)

    :returns: (marcados agora, ausentes no sync-dir)
    """
    # logger
    M_LOG.debug(">> mark_received")

    ls_now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    llst_present = []
    li_absent = 0

    for ls_path in flst_paths:
        if (fpth_sync_dir / ls_path).is_file():
            llst_present.append((ls_now, ls_path))

        else:
            li_absent += 1

    lconn = sqlite3.connect(fs_dbase_path, timeout=10)

    try:
        lconn.execute("PRAGMA journal_mode = WAL")
        sc.check_schema(lconn, fs_dbase_path)

        lcursor = lconn.executemany(
            f"UPDATE {ct.CS_TABLE} SET received_at = ? WHERE fullpath = ? AND received_at IS NULL",
            llst_present)

        li_marked = lcursor.rowcount
        lconn.commit()

    finally:
        lconn.close()

    # ok
    return li_marked, li_absent

# ─────────────────────────────────────────────────────────────────────────────────────
def main() -> int:
    """
    drive app

    :returns: 0 em caso de sucesso (mesmo que nenhuma linha válida tenha
              sido lida), 1 se a listagem tiver caminho absoluto ou se a
              gravação no catalog.db falhar (em --received: só a falha de banco)
    """
    # logger
    M_LOG.debug(">> main")

    # parse args
    largs = arg_parse()

    if largs.received:
        # stdin = lista de transferência do vol_sync.sh (um caminho por linha)
        llst_paths = [ls.strip() for ls in sys.stdin if ls.strip()]

        try:
            li_marked, li_absent = mark_received(largs.dbase, llst_paths, largs.sync_dir)

        # em caso de erro,...
        except sqlite3.Error as lerr:
            # logger
            M_LOG.error("falha ao marcar recepção no catalog.db (%s): %s", largs.dbase, lerr)
            # quit fail
            return 1

        # logger
        M_LOG.info("recepção: %d da lista, %d recebidos agora, %d ausentes no sync-dir",
                   len(llst_paths), li_marked, li_absent)
        # ok
        return 0

    try:
        # lê e interpreta as linhas vindas do pipe (stdin)
        llst_rows = parse_lines(sys.stdin)

    # caminho absoluto na listagem
    except ValueError as lerr:
        # logger
        M_LOG.warning("listagem recusada, nada gravado: %s", lerr)
        # quit fail -- vol_sync.sh não baixa (nem remove) nada sem o registro
        return 1

    if not llst_rows:
        # nada a gravar
        return 0

    try:
        # grava no catalog.db compartilhado
        li_new_rows = write_observations(largs.dbase, llst_rows)

    # em caso de erro,...
    except sqlite3.Error as lerr:
        # logger
        M_LOG.warning("falha ao gravar no catalog.db (%s): %s", largs.dbase, lerr)
        # quit fail -- vol_sync.sh não baixa (nem remove) nada sem o registro
        return 1

    # logger
    M_LOG.info("observações: %d listadas, %d novas", len(llst_rows), li_new_rows)

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
