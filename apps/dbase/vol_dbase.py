# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

vol_dbase
acesso à tabela volumes do catalog.db compartilhado: registro dos .mvol
(volScan.py) e retenção (volPurge.py).  Cria também processing_log e
radar_sites.

o schema (DDL) e os códigos de status são um contrato -- qualquer mudança
precisa ser replicada lá.  Aqui volumes.status só nasce NEW (colunas de
conversão has_cappi, cappi_path, rain/valid_fraction e os status 1-5 ficam
no DDL por contrato, preenchidas só nas linhas de antes da mudança).

todo instante é UTC: timestamp = epoch do horário (UTC) no nome do .mvol;
created_at/updated_at = datetime.now(timezone.utc).isoformat().

2026.out  mlabru  refatoração para legibilidade (API e DDL inalterados):
                  condição "pendente" de purge_candidates() em
                  _pending_condition(); transaction()/transaction_write()
                  sobre um gerador comum, _run_transaction()

2026.set  mlabru  - volumes_to_process, reset_stale_processing, mark_done,
                    update_status, count_failures, insert_log,
                    upsert_radar_site e CS_STEP_PROCESS/CS_LOG_* removidos
                  - retenção: purge_candidates() (volumes antigos com .mvol)
                    e mark_mvol_removed(); mark_done() não mexe mais em
                    has_mvol (só a retenção apaga o .mvol)

2026.set  mlabru  initial version (Linux/Python)
"""
# < imports >──────────────────────────────────────────────────────────────────────────

# python library
from __future__ import annotations

import contextlib
import datetime
import logging
import sqlite3
import typing

# < constants >────────────────────────────────────────────────────────────────────────

# status do pipeline (idênticos a nc_database.CI_STATUS_*)
CI_STATUS_NEW          = 0
CI_STATUS_PROCESSING   = 1
CI_STATUS_DONE         = 2
CI_STATUS_FAILED       = 3
CI_STATUS_INTERPOLATED = 4
CI_STATUS_PREDICTED    = 5

# volumes com .mvol ainda sem produto final no preset ativo.  Contrato: a
# retenção não apaga o .mvol de um volume que está nela.  Só lida aqui,
# nunca criada
CS_VIEW_PENDING = "cappi_pending"

# SQL — criação das tabelas e índices
CS_CREATE_VOLUMES = """
CREATE TABLE IF NOT EXISTS volumes (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    radar          TEXT    NOT NULL,
    alcance        INTEGER NOT NULL,
    timestamp      INTEGER NOT NULL,
    fullpath       TEXT    NOT NULL,
    filesize       INTEGER,
    sha1           TEXT,
    has_mvol       INTEGER DEFAULT 1,
    has_cappi      INTEGER DEFAULT 0,
    cappi_path     TEXT,
    interpolated   INTEGER DEFAULT 0,
    predicted      INTEGER DEFAULT 0,
    status         INTEGER DEFAULT 0,
    rain_fraction  REAL,
    valid_fraction REAL,
    created_at     TEXT,
    updated_at     TEXT,
    UNIQUE(radar, alcance, timestamp))"""

CS_CREATE_LOG = """
CREATE TABLE IF NOT EXISTS processing_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    radar      TEXT NOT NULL,
    alcance    INTEGER NOT NULL,
    timestamp  INTEGER NOT NULL,
    step       TEXT,
    status     INTEGER,
    message    TEXT,
    created_at TEXT)"""

CS_CREATE_RADAR_SITES = """
CREATE TABLE IF NOT EXISTS radar_sites (
    radar      TEXT PRIMARY KEY,
    latitude   REAL NOT NULL,
    longitude  REAL NOT NULL,
    altitude   REAL NOT NULL,
    updated_at TEXT)"""

CS_CREATE_INDEX_1 = "CREATE INDEX IF NOT EXISTS idx_timestamp        ON volumes(timestamp)"
CS_CREATE_INDEX_2 = "CREATE INDEX IF NOT EXISTS idx_status           ON volumes(status)"
CS_CREATE_INDEX_3 = "CREATE INDEX IF NOT EXISTS idx_radar_timestamp  ON volumes(radar, alcance, timestamp)"

MT_CREATE_ALL = (CS_CREATE_VOLUMES, CS_CREATE_LOG, CS_CREATE_RADAR_SITES,
                 CS_CREATE_INDEX_1, CS_CREATE_INDEX_2, CS_CREATE_INDEX_3)

# < logging >──────────────────────────────────────────────────────────────────────────

# logger
M_LOG = logging.getLogger(__name__)
M_LOG.setLevel(logging.INFO)

# -------------------------------------------------------------------------------------
def utc_now_iso() -> str:
    """
    instante atual em UTC, formato ISO 8601
    """
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

# < CVolDB >───────────────────────────────────────────────────────────────────────────

class CVolDB:
    """
    conexão com o catalog.db para as tabelas de processamento de volumes.
    use através dos context managers transaction()/transaction_write().
    """
    # ---------------------------------------------------------------------------------
    def __init__(self, fs_dbase_path: str):
        """
        abre a conexão (WAL, timeout de lock) e garante o schema

        :param fs_dbase_path: caminho do catalog.db
        """
        # logger
        M_LOG.debug(">> __init__")

        # timeout=10 evita falha imediata em contenção de lock
        self.conn = sqlite3.connect(fs_dbase_path, timeout=10)

        # rows acessíveis por nome de coluna
        self.conn.row_factory = sqlite3.Row

        # modo WAL para melhor concorrência de leitura
        self.conn.execute("PRAGMA journal_mode = WAL")

        # garante schema (idempotente)
        for ls_sql in MT_CREATE_ALL:
            self.conn.execute(ls_sql)

        self.conn.commit()

        # create cursor
        self.cursor = self.conn.cursor()

    # ---------------------------------------------------------------------------------
    def begin(self) -> None:
        """
        inicia uma transação de leitura (BEGIN DEFERRED)
        """
        self.cursor.execute("BEGIN")

    # ---------------------------------------------------------------------------------
    def begin_write(self) -> None:
        """
        inicia uma transação de escrita (BEGIN IMMEDIATE), adquirindo o lock
        de escrita logo no início
        """
        self.cursor.execute("BEGIN IMMEDIATE")

    # ---------------------------------------------------------------------------------
    def close(self) -> None:
        """
        fecha a conexão
        """
        self.conn.close()

    # ---------------------------------------------------------------------------------
    def commit(self) -> None:
        """
        confirma a transação corrente
        """
        self.conn.commit()

    # ---------------------------------------------------------------------------------
    def rollback(self) -> None:
        """
        desfaz a transação corrente
        """
        self.conn.rollback()

    # ---------------------------------------------------------------------------------
    def get_volume(self, fs_radar: str, fi_alcance: int,
                   fi_timestamp: int) -> typing.Optional[sqlite3.Row]:
        """
        registro completo de um volume pelo identificador composto, ou None
        """
        self.cursor.execute("""SELECT *
                               FROM   volumes
                               WHERE  radar     = ?
                               AND    alcance   = ?
                               AND    timestamp = ?""", (fs_radar, fi_alcance, fi_timestamp))

        # ok
        return self.cursor.fetchone()

    # ---------------------------------------------------------------------------------
    def insert_volume(self, fs_radar: str, fi_alcance: int, fi_timestamp: int,
                      fs_fullpath: str, fi_filesize: int, fs_sha1: str | None) -> None:
        """
        insere um novo volume com status NEW (has_mvol=1, has_cappi=0)
        """
        ls_now = utc_now_iso()

        self.cursor.execute("""INSERT INTO volumes (radar, alcance, timestamp, fullpath,
                                                    filesize, sha1, has_mvol, has_cappi,
                                                    status, created_at, updated_at)
                               VALUES (?, ?, ?, ?, ?, ?, 1, 0, ?, ?, ?)""",
                            (fs_radar, fi_alcance, fi_timestamp, fs_fullpath, fi_filesize,
                             fs_sha1, CI_STATUS_NEW, ls_now, ls_now))

    # ---------------------------------------------------------------------------------
    def has_pending_view(self) -> bool:
        """
        True se já criou a view cappi_pending neste banco
        """
        self.cursor.execute("SELECT 1 FROM sqlite_master WHERE type = 'view' AND name = ?",
                            (CS_VIEW_PENDING,))

        # ok
        return self.cursor.fetchone() is not None

    # ---------------------------------------------------------------------------------
    def mark_mvol_removed(self, fs_radar: str, fi_alcance: int, fi_timestamp: int) -> None:
        """
        registra que o .mvol do volume não existe mais (has_mvol=0)
        """
        self.cursor.execute("""UPDATE volumes
                               SET    has_mvol   = 0,
                                      updated_at = ?
                               WHERE  radar      = ?
                               AND    alcance    = ?
                               AND    timestamp  = ?""",
                            (utc_now_iso(), fs_radar, fi_alcance, fi_timestamp))

    # ---------------------------------------------------------------------------------
    def _pending_condition(self) -> tuple:
        """
        condição SQL (sobre o alias v de volumes) que diz se um volume ainda
        está pendente de conversão:

        - com a view cappi_pending (nowcast instalado neste banco): o volume
          está na view;
        - sem a view: status fora de DONE/FAILED (estado do antigo
          volProcess daqui).

        :returns: (texto SQL, tupla de parâmetros desse texto)
        """
        if self.has_pending_view():
            ls_sql = (f"EXISTS (SELECT 1 FROM {CS_VIEW_PENDING} c "
                      "WHERE c.radar = v.radar AND c.alcance = v.alcance "
                      "AND c.timestamp = v.timestamp)")
            # ok
            return ls_sql, ()

        # ok
        return "v.status NOT IN (?, ?)", (CI_STATUS_DONE, CI_STATUS_FAILED)

    # ---------------------------------------------------------------------------------
    def purge_candidates(self, fi_cutoff_ts: int, fi_hard_cutoff_ts: int | None) -> list[dict]:
        """
        volumes cujo .mvol pode ser apagado pela retenção (volPurge.py).  um
        volume é candidato quando, ao mesmo tempo:

        - ainda tem o .mvol (has_mvol=1);
        - não é sintético (status fora de INTERPOLATED/PREDICTED);
        - é mais antigo que fi_cutoff_ts (horário do nome, UTC);
        - não está pendente (_pending_condition) -- OU está pendente mas é
          mais antigo que fi_hard_cutoff_ts (limite de disco; None = nunca
          força).

        :param fi_cutoff_ts: corte de retenção (epoch UTC)
        :param fi_hard_cutoff_ts: corte forçado (epoch UTC) ou None

        :returns: list[dict] (radar, alcance, timestamp, fullpath, status,
                  pending), ordenados por timestamp
        """
        ls_pending, lt_pending_params = self._pending_condition()

        # sem limite de disco: -1 faz "timestamp < -1" ser sempre falso,
        # então nenhum pendente é forçado
        li_hard_cutoff = -1

        if fi_hard_cutoff_ts is not None:
            li_hard_cutoff = fi_hard_cutoff_ts

        ls_sql = f"""SELECT v.radar, v.alcance, v.timestamp, v.fullpath, v.status,
                            ({ls_pending}) AS pending
                     FROM   volumes v
                     WHERE  v.has_mvol = 1
                     AND    v.status NOT IN (?, ?)
                     AND    v.timestamp < ?
                     AND    (NOT ({ls_pending}) OR v.timestamp < ?)
                     ORDER BY v.timestamp"""

        # os parâmetros seguem a ordem dos "?" no texto acima: a condição de
        # pendente aparece duas vezes (no SELECT e no WHERE)
        lt_params = (*lt_pending_params,
                     CI_STATUS_INTERPOLATED, CI_STATUS_PREDICTED,
                     fi_cutoff_ts,
                     *lt_pending_params,
                     li_hard_cutoff)

        self.cursor.execute(ls_sql, lt_params)

        llst_candidates = []

        for lrow in self.cursor.fetchall():
            ldct_candidate = dict(lrow)
            # SQLite devolve 0/1: converte para bool
            ldct_candidate["pending"] = bool(lrow["pending"])
            llst_candidates.append(ldct_candidate)

        # ok
        return llst_candidates

    # ---------------------------------------------------------------------------------
    def update_volume(self, fs_radar: str, fi_alcance: int, fi_timestamp: int,
                      fs_fullpath: str, fi_filesize: int, fs_sha1: str | None) -> None:
        """
        atualiza localização/integridade de um volume já existente e marca
        has_mvol=1 (o .mvol está presente)
        """
        self.cursor.execute("""UPDATE volumes
                               SET    fullpath   = ?,
                                      filesize   = ?,
                                      sha1       = ?,
                                      has_mvol   = 1,
                                      updated_at = ?
                               WHERE  radar      = ?
                               AND    alcance    = ?
                               AND    timestamp  = ?""",
                            (fs_fullpath, fi_filesize, fs_sha1, utc_now_iso(),
                             fs_radar, fi_alcance, fi_timestamp))

# < context managers >─────────────────────────────────────────────────────────────────

def _run_transaction(fs_dbase_path: str, fb_write: bool):
    """
    gerador comum às duas transações: abre a conexão, inicia a transação,
    entrega o CVolDB ao bloco "with", e no fim faz commit (sucesso) ou
    rollback (exceção), sempre fechando a conexão

    :param fs_dbase_path: caminho do catalog.db
    :param fb_write: True = BEGIN IMMEDIATE (lock de escrita já no início);
                     False = BEGIN (deferred, leitura)
    """
    ldb = CVolDB(fs_dbase_path)

    try:
        if fb_write:
            ldb.begin_write()

        else:
            ldb.begin()

        yield ldb
        ldb.commit()

    except Exception:
        ldb.rollback()
        raise

    finally:
        ldb.close()

# -------------------------------------------------------------------------------------
@contextlib.contextmanager
def transaction(fs_dbase_path: str):
    """
    transação de leitura (BEGIN DEFERRED): commit em sucesso, rollback em
    exceção, fecha a conexão ao final

    uso:
        with transaction(path) as ldb:
            lrow = ldb.get_volume(...)
    """
    yield from _run_transaction(fs_dbase_path, fb_write=False)

# -------------------------------------------------------------------------------------
@contextlib.contextmanager
def transaction_write(fs_dbase_path: str):
    """
    transação de escrita (BEGIN IMMEDIATE): commit em sucesso, rollback em
    exceção, fecha a conexão ao final.  mantenha o bloco curto: enquanto
    ele roda, nenhum outro processo (ex.: nwcConvert) consegue gravar

    uso:
        with transaction_write(path) as ldb:
            ldb.insert_volume(...)
    """
    yield from _run_transaction(fs_dbase_path, fb_write=True)

# < the end >──────────────────────────────────────────────────────────────────────────
