# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

test_volDBWriter
testes unitários de volDBWriter (persistência das observações de
list_remote_files() no catalog.db)

2026.set  mlabru  fullpath relativo a REMOTE_DIR; caminho absoluto recusado
2026.set  mlabru  obs_time renomeada para timestamp (inteiro); migração do nome
2026.set  mlabru  obs_time (tempo do nome, UTC) e migração de base antiga
2026.set  mlabru  CS_TABLE agora vem de vol_catalog
2026.ago  mlabru  initial version (Linux/Python)
"""
# < imports >──────────────────────────────────────────────────────────────────────────

# python library
import datetime
import sqlite3

# pytest
import pytest

# model
import dbase.vol_catalog as ct
import volDBWriter as vcw

# path/timestamp de referência (00:00:23 UTC de 2026-04-12)
MS_PATH = "Cangucu/250/CGU-250--2026-04-12--00-00-23.mvol"
MI_TS = int(datetime.datetime(2026, 4, 12, 0, 0, 23, tzinfo=datetime.timezone.utc).timestamp())

# ─────────────────────────────────────────────────────────────────────────────────────
def test_parse_lines_ignora_linhas_vazias_e_malformadas(caplog):
    """
    linhas vazias são ignoradas silenciosamente; linhas sem separador
    '|' ou com mtime não numérico são ignoradas com um warning
    """
    llst_linhas = [
        "1700000000.0|Cangucu/250/CGU-250--2026-04-12--00-00-23.mvol",
        "",
        "   ",
        "linha sem separador",
        "abc|Gama/400/GAF-400--2026-04-12--00-01-00.mvol",
        # sem caminho
        "1700000000.0|",
    ]

    llst_rows = vcw.parse_lines(llst_linhas)

    assert 1 == len(llst_rows)
    assert (MS_PATH, 1700000000.0, MI_TS) == llst_rows[0]


def test_parse_lines_timestamp_vem_do_nome_e_nao_do_mtime():
    """
    timestamp é o epoch UTC do nome, independente do mtime (relógio do
    servidor); nome fora do padrão -> None, mas a observação é mantida
    """
    llst_rows = vcw.parse_lines([f"42.0|{MS_PATH}", "43.0|x/y/lixo.mvol"])

    assert [(MS_PATH, 42.0, MI_TS), ("x/y/lixo.mvol", 43.0, None)] == llst_rows


def test_parse_lines_recusa_caminho_absoluto():
    """
    caminho absoluto (listagem sem find -printf '%P') não é só descartado:
    recusa a listagem inteira -- gravá-la duplicaria as linhas já
    registradas com o caminho relativo
    """
    with pytest.raises(ValueError):
        vcw.parse_lines([f"42.0|{MS_PATH}", f"43.0|/home/webpca/radar/{MS_PATH}"])


def test_write_observations_grava_e_cria_schema(tmp_path):
    """
    write_observations cria a tabela/índice se não existirem e grava as
    linhas com source='mvol'
    """
    ls_dbase = str(tmp_path / "catalog.db")

    llst_rows = [(MS_PATH, 1700000000.0, MI_TS)]
    li_gravadas = vcw.write_observations(ls_dbase, llst_rows)

    assert 1 == li_gravadas

    lconn = sqlite3.connect(ls_dbase)
    llst = lconn.execute(
        f"SELECT fullpath, mtime, timestamp, source FROM {ct.CS_TABLE}").fetchall()
    lconn.close()

    assert [(MS_PATH, 1700000000.0, MI_TS, "mvol")] == llst


def test_write_observations_e_idempotente_por_fullpath(tmp_path):
    """
    gravar a mesma fullpath duas vezes (ex.: duas rodadas do downloader)
    não duplica a linha -- INSERT OR IGNORE
    """
    ls_dbase = str(tmp_path / "catalog.db")
    vcw.write_observations(ls_dbase, [(MS_PATH, 1700000000.0, MI_TS)])
    vcw.write_observations(ls_dbase, [(MS_PATH, 1700000000.0, MI_TS)])

    lconn = sqlite3.connect(ls_dbase)
    li_total = lconn.execute(f"SELECT COUNT(*) FROM {ct.CS_TABLE}").fetchone()[0]
    lconn.close()

    assert 1 == li_total


def test_write_observations_migra_base_antiga_e_preenche_timestamp(tmp_path):
    """
    base criada antes de timestamp (schema antigo, linha gravada pelo
    monrad quando ele ainda gravava): ganha a coluna e a linha existente recebe o timestamp do nome,
    sem duplicar nem alterar o mtime/source originais
    """
    ls_dbase = str(tmp_path / "catalog.db")

    lconn = sqlite3.connect(ls_dbase)
    lconn.execute(f"CREATE TABLE {ct.CS_TABLE} (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                  "fullpath TEXT NOT NULL UNIQUE, mtime REAL NOT NULL, "
                  "source TEXT NOT NULL, created_at TEXT)")
    lconn.execute(f"INSERT INTO {ct.CS_TABLE} (fullpath, mtime, source) VALUES (?, ?, ?)",
                  (MS_PATH, 1.0, "monrad"))
    lconn.commit()
    lconn.close()

    assert 0 == vcw.write_observations(ls_dbase, [(MS_PATH, 2.0, MI_TS)])

    lconn = sqlite3.connect(ls_dbase)
    llst = lconn.execute(
        f"SELECT fullpath, mtime, timestamp, source FROM {ct.CS_TABLE}").fetchall()
    lconn.close()

    assert [(MS_PATH, 1.0, MI_TS, "monrad")] == llst


def test_ensure_schema_renomeia_obs_time_para_timestamp(tmp_path):
    """
    base com a coluna no nome anterior (obs_time) e seu índice: a coluna é
    renomeada para timestamp com os valores preservados, e o índice antigo
    dá lugar ao novo
    """
    ls_dbase = str(tmp_path / "catalog.db")

    lconn = sqlite3.connect(ls_dbase)
    lconn.execute(f"CREATE TABLE {ct.CS_TABLE} (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                  "fullpath TEXT NOT NULL UNIQUE, mtime REAL NOT NULL, obs_time REAL, "
                  "source TEXT NOT NULL, created_at TEXT)")
    lconn.execute("CREATE INDEX vol_raw_observations_idx_obs_time "
                  f"ON {ct.CS_TABLE}(obs_time)")
    lconn.execute(f"INSERT INTO {ct.CS_TABLE} (fullpath, mtime, obs_time, source) "
                  "VALUES (?, ?, ?, ?)", (MS_PATH, 1.0, float(MI_TS), "mvol"))
    lconn.commit()

    ct.ensure_schema(lconn)
    lconn.commit()

    lset_cols = {lt[1] for lt in lconn.execute(f"PRAGMA table_info({ct.CS_TABLE})")}
    lset_idx = {lt[1] for lt in lconn.execute(f"PRAGMA index_list({ct.CS_TABLE})")}
    li_ts = lconn.execute(f"SELECT timestamp FROM {ct.CS_TABLE}").fetchone()[0]
    lconn.close()

    assert "timestamp" in lset_cols and "obs_time" not in lset_cols
    assert "vol_raw_observations_idx_timestamp" in lset_idx
    assert "vol_raw_observations_idx_obs_time" not in lset_idx
    assert MI_TS == li_ts


def test_main_sem_linhas_validas_nao_toca_no_banco(tmp_path, monkeypatch):
    """
    se a stdin não tiver nenhuma linha válida, main() não deve nem
    tentar abrir o catalog.db
    """
    ls_dbase = str(tmp_path / "catalog.db")

    monkeypatch.setattr(vcw, "arg_parse",
                        lambda: type("Args", (), {"dbase": ls_dbase})())
    monkeypatch.setattr("sys.stdin", iter([""]))

    li_rc = vcw.main()

    assert 0 == li_rc
    assert not (tmp_path / "catalog.db").exists()


def test_main_caminho_absoluto_retorna_1_e_nao_toca_no_banco(tmp_path, monkeypatch):
    """
    listagem com caminho absoluto: main() retorna 1 (vol_sync.sh aborta sem
    baixar/remover) e o catalog.db nem é criado
    """
    ls_dbase = str(tmp_path / "catalog.db")

    monkeypatch.setattr(vcw, "arg_parse",
                        lambda: type("Args", (), {"dbase": ls_dbase})())
    monkeypatch.setattr("sys.stdin", iter([f"42.0|/home/webpca/radar/{MS_PATH}\n"]))

    li_rc = vcw.main()

    assert 1 == li_rc
    assert not (tmp_path / "catalog.db").exists()

# < the end >──────────────────────────────────────────────────────────────────────────
