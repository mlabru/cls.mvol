# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

volDBList
lista o conteúdo da tabela de observações brutas (vol_catalog.CS_TABLE) do
catalog.db compartilhado, gravada por volDBWriter.py.

abre o banco somente para leitura (mode=ro), para nunca criar o arquivo nem
disputar lock de escrita com vol_sync.sh / monrad.

2026.out  mlabru  refatoração para legibilidade: list_observations()
                  dividido em _build_where_clause, _select_time_column,
                  _count_rows, _select_rows e _print_rows
2026.set  mlabru  coluna obs_time renomeada para timestamp; base ainda não
                  migrada (obs_time) continua legível
2026.set  mlabru  coluna obs_time (tempo do nome, UTC) na listagem e na
                  ordenação; base antiga sem a coluna continua legível
2026.set  mlabru  initial version (Linux/Python)
"""
# < imports >──────────────────────────────────────────────────────────────────────────

# python library
import argparse
import datetime
import logging
import pathlib
import sqlite3
import sys

# locals
import dbase.vol_catalog as ct

# < constants >────────────────────────────────────────────────────────────────────────

# catalog.db padrão (data/dbase/catalog.db, relativo à raiz do projeto)
MPTH_DBASE = pathlib.Path(__file__).resolve().parent.parent / "data" / "dbase" / "catalog.db"

# < logging >──────────────────────────────────────────────────────────────────────────

# logger
M_LOG = logging.getLogger(__name__)
M_LOG.setLevel(logging.INFO)

# ─────────────────────────────────────────────────────────────────────────────────────
def arg_parse():
    """
    lê os argumentos da linha de comando

    :returns: argparse.Namespace com dbase, filter, source, limit, reverse
              e count
    """
    # logger
    M_LOG.debug(">> arg_parse")

    # create parser
    lparser = argparse.ArgumentParser(
                 description=f"Lista o conteúdo da tabela {ct.CS_TABLE} do catalog.db.")

    # caminho do catalog.db compartilhado
    lparser.add_argument("dbase", nargs='?', default=str(MPTH_DBASE), type=str,
                         help=f"caminho do catalog.db (default: {MPTH_DBASE}).")

    # filtros
    lparser.add_argument("-f", "--filter", dest="filter", type=str, default=None,
                         help="só fullpath contendo este texto (ex.: CGU-400).")
    lparser.add_argument("-s", "--source", dest="source", type=str, default=None,
                         help="só observações desta origem (ex.: mvol).")
    lparser.add_argument("-n", "--limit", dest="limit", type=int, default=None,
                         help="número máximo de linhas.")
    lparser.add_argument("-r", "--reverse", dest="reverse", action="store_true",
                         help="mais recentes primeiro (ordem decrescente de timestamp).")
    lparser.add_argument("-c", "--count", dest="count", action="store_true",
                         help="mostra só a contagem de linhas.")

    # ok
    return lparser.parse_args()

# ─────────────────────────────────────────────────────────────────────────────────────
def fmt_mtime(ff_mtime: float | None) -> str:
    """
    converte epoch (mtime/timestamp) em data/hora UTC legível (mesmo
    formato de volAudit.fmt_epoch)

    :param ff_mtime: epoch em segundos, ou None (timestamp NULL)

    :returns: "AAAA-MM-DD HH:MM:SS", ou "-" se ff_mtime for None
    """
    # sem valor (timestamp NULL)
    if ff_mtime is None:
        return "-"

    ldt_utc = datetime.datetime.fromtimestamp(ff_mtime, datetime.timezone.utc)

    # ok
    return ldt_utc.strftime("%Y-%m-%d %H:%M:%S")

# ─────────────────────────────────────────────────────────────────────────────────────
def _build_where_clause(fs_filter: str | None, fs_source: str | None) -> tuple:
    """
    monta a cláusula WHERE dos filtros (com parâmetros "?", nunca texto do
    usuário colado no SQL)

    :returns: (" WHERE ..." ou "", lista de parâmetros)
    """
    llst_conditions = []
    llst_params = []

    if fs_filter:
        llst_conditions.append("fullpath LIKE ?")
        llst_params.append(f"%{fs_filter}%")

    if fs_source:
        llst_conditions.append("source = ?")
        llst_params.append(fs_source)

    if not llst_conditions:
        return "", llst_params

    # ok
    return " WHERE " + " AND ".join(llst_conditions), llst_params

# ─────────────────────────────────────────────────────────────────────────────────────
def _select_time_column(fconn) -> str:
    """
    nome da coluna com o horário do nome do arquivo.  uma base ainda não
    migrada usa o nome anterior (obs_time); uma base mais antiga não tem a
    coluna (lista NULL).  mode=ro não permite migrar aqui

    :returns: "timestamp", "obs_time" ou "NULL"
    """
    lset_columns = set()

    for lt_row in fconn.execute(f"PRAGMA table_info({ct.CS_TABLE})"):
        # coluna 1 do PRAGMA table_info é o nome
        lset_columns.add(lt_row[1])

    for ls_column in ("timestamp", "obs_time"):
        if ls_column in lset_columns:
            return ls_column

    # ok
    return "NULL"

# ─────────────────────────────────────────────────────────────────────────────────────
def _count_rows(fconn, fs_where: str, flst_params: list) -> int:
    """
    número de observações que passam pelos filtros
    """
    ls_sql = f"SELECT COUNT(*) FROM {ct.CS_TABLE}{fs_where}"

    # ok
    return fconn.execute(ls_sql, flst_params).fetchone()[0]

# ─────────────────────────────────────────────────────────────────────────────────────
def _select_rows(fconn, fs_where: str, flst_params: list, fi_limit: int | None,
                 fb_reverse: bool) -> list:
    """
    lê as observações, ordenadas pelo horário do nome (ou pelo mtime, se
    ele faltar)

    :returns: [(id, timestamp, mtime, source, created_at, fullpath)]
    """
    ls_time_column = _select_time_column(fconn)

    ls_order = "ASC"

    if fb_reverse:
        ls_order = "DESC"

    ls_sql = (f"SELECT id, {ls_time_column}, mtime, source, created_at, fullpath "
              f"FROM {ct.CS_TABLE}{fs_where} "
              f"ORDER BY COALESCE({ls_time_column}, mtime) {ls_order}")

    # cópia: não altera a lista do chamador
    llst_params = list(flst_params)

    if fi_limit is not None:
        ls_sql += " LIMIT ?"
        llst_params.append(fi_limit)

    # ok
    return fconn.execute(ls_sql, llst_params).fetchall()

# ─────────────────────────────────────────────────────────────────────────────────────
def _print_rows(flst_rows: list) -> None:
    """
    imprime as observações em colunas, com cabeçalho e rodapé
    """
    print(f"{'id':>8}  {'timestamp (UTC)':19}  {'mtime (UTC)':19}  {'source':8}  "
          f"{'created_at':32}  fullpath")
    print(f"{'-' * 8}  {'-' * 19}  {'-' * 19}  {'-' * 8}  {'-' * 32}  {'-' * 8}")

    for li_id, lf_timestamp, lf_mtime, ls_source, ls_created, ls_fullpath in flst_rows:
        print(f"{li_id:>8}  {fmt_mtime(lf_timestamp):19}  {fmt_mtime(lf_mtime):19}  "
              f"{ls_source:8}  {ls_created or '':32}  {ls_fullpath}")

    print(f"\n{len(flst_rows)} linha(s)")

# ─────────────────────────────────────────────────────────────────────────────────────
def list_observations(fs_dbase_path: str, fs_filter: str = None, fs_source: str = None,
                      fi_limit: int = None, fb_reverse: bool = False,
                      fb_count: bool = False) -> int:
    """
    lista as observações (ou só a contagem) na saída padrão

    :param fs_dbase_path: caminho do catalog.db (aberto somente leitura)
    :param fs_filter: só fullpath contendo este texto
    :param fs_source: só observações desta origem
    :param fi_limit: número máximo de linhas (None = todas)
    :param fb_reverse: True = mais recentes primeiro
    :param fb_count: True = imprime só a contagem

    :raises sqlite3.Error: banco/tabela ilegível

    :returns: número de linhas encontradas
    """
    # logger
    M_LOG.debug(">> list_observations")

    ls_where, llst_params = _build_where_clause(fs_filter, fs_source)

    # abre somente para leitura (não cria o arquivo se não existir)
    lconn = sqlite3.connect(f"file:{fs_dbase_path}?mode=ro", uri=True, timeout=10)

    try:
        if fb_count:
            li_count = _count_rows(lconn, ls_where, llst_params)
            print(li_count)
            # ok
            return li_count

        llst_rows = _select_rows(lconn, ls_where, llst_params, fi_limit, fb_reverse)

    finally:
        lconn.close()

    _print_rows(llst_rows)

    # ok
    return len(llst_rows)

# ─────────────────────────────────────────────────────────────────────────────────────
def main() -> int:
    """
    drive app

    :returns: 0 em caso de sucesso, 1 se o banco/tabela não puder ser lido
    """
    # logger
    M_LOG.debug(">> main")

    # parse args
    largs = arg_parse()

    try:
        # lista as observações
        list_observations(largs.dbase, largs.filter, largs.source,
                          largs.limit, largs.reverse, largs.count)

    # em caso de erro (banco inexistente, tabela ausente, ...)
    except sqlite3.Error as lerr:
        # logger
        M_LOG.error("falha ao ler %s (%s): %s", ct.CS_TABLE, largs.dbase, lerr)
        # quit fail
        return 1

    # saída fechada antes do fim (ex.: | head)
    except BrokenPipeError:
        # ok
        return 0

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
