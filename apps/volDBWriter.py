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

o schema vive só em vol_catalog.py (compartilhado por symlink).

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
import sqlite3
import sys

# locals
import radar.rd_mvol as mv
import dbase.vol_catalog as ct

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

    :returns: argparse.Namespace com dbase
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

    # ok
    return lparser.parse_args()

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
    abre o catalog.db compartilhado (WAL, garante/migra schema) e grava as
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

    # parâmetros do INSERT: (fullpath, mtime, timestamp, source, created_at)
    llst_insert_params = []

    for ls_fullpath, lf_mtime, li_timestamp in flst_rows:
        llst_insert_params.append((ls_fullpath, lf_mtime, li_timestamp, CS_SOURCE, ls_now))

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

        ct.ensure_schema(lconn)

        lcursor = lconn.executemany(
            f"INSERT OR IGNORE INTO {ct.CS_TABLE} (fullpath, mtime, timestamp, source, created_at) "
            f"VALUES (?, ?, ?, ?, ?)", llst_insert_params)

        li_new_rows = lcursor.rowcount

        lconn.executemany(
            f"UPDATE {ct.CS_TABLE} SET timestamp = ? WHERE fullpath = ? AND timestamp IS NULL",
            llst_update_params)

        lconn.commit()

    finally:
        lconn.close()

    # ok
    return li_new_rows

# ─────────────────────────────────────────────────────────────────────────────────────
def main() -> int:
    """
    drive app

    :returns: 0 em caso de sucesso (mesmo que nenhuma linha válida tenha
              sido lida), 1 se a listagem tiver caminho absoluto ou se a
              gravação no catalog.db falhar
    """
    # logger
    M_LOG.debug(">> main")

    # parse args
    largs = arg_parse()

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
        write_observations(largs.dbase, llst_rows)

    # em caso de erro,...
    except sqlite3.Error as lerr:
        # logger
        M_LOG.warning("falha ao gravar no catalog.db (%s): %s", largs.dbase, lerr)
        # quit fail -- vol_sync.sh não baixa (nem remove) nada sem o registro
        return 1

    # ok
    return 0

# ─────────────────────────────────────────────────────────────────────────────────────
# this is the bootstrap process

if "__main__" == __name__:
    # logger
    logging.basicConfig(datefmt="%Y/%m/%d %H:%M",
                        format="%(asctime)s %(message)s",
                        level=logging.INFO)

    # run
    sys.exit(main())

# < the end >──────────────────────────────────────────────────────────────────────────
