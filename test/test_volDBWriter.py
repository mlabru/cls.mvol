# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

test_volDBWriter
testes unitários de volDBWriter (persistência das observações de
list_remote_files() no catalog.db)

2026.nov  mlabru  histórico de recepção: reenvio, mark_received, --received
2026.nov  mlabru  banco migrado pela fixture; recusa banco não migrado; a
                  migração obs_time -> timestamp foi para cls.common/test_schema
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
import cls_common.dbase.vol_catalog as ct
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


def test_write_observations_grava(tmp_path):
    """
    write_observations grava as linhas com source='mvol' (no banco migrado
    pelo deploy -- aqui, pela fixture catalog_migrado)
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


def test_write_observations_preenche_timestamp_de_linha_antiga(tmp_path):
    """
    linha gravada antes da coluna timestamp (pelo monrad, quando ele ainda
    gravava; a migração 1 do schema deu a coluna, NULL): recebe o timestamp
    do nome, sem duplicar nem alterar o mtime/source originais.  A migração
    da coluna em si é testada em cls.common/test/test_schema.py
    """
    ls_dbase = str(tmp_path / "catalog.db")

    lconn = sqlite3.connect(ls_dbase)
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


def test_write_observations_recusa_banco_nao_migrado(tmp_path):
    """
    banco fora da versão de esquema (aqui: um arquivo novo, versão 0): não
    cria tabela nenhuma, levanta -- e main() devolve 1, o que faz o
    vol_sync.sh não baixar nem remover nada
    """
    ls_dbase = str(tmp_path / "nao_migrado.db")

    with pytest.raises(sqlite3.DatabaseError, match="versão 0"):
        vcw.write_observations(ls_dbase, [(MS_PATH, 1.0, MI_TS)])

    lconn = sqlite3.connect(ls_dbase)
    assert [] == lconn.execute("SELECT name FROM sqlite_master").fetchall()
    lconn.close()


def test_main_sem_linhas_validas_nao_toca_no_banco(tmp_path, monkeypatch):
    """
    se a stdin não tiver nenhuma linha válida, main() não deve nem
    tentar abrir o catalog.db
    """
    ls_dbase = str(tmp_path / "nao_existe.db")

    monkeypatch.setattr(vcw, "arg_parse",
                        lambda: type("Args", (), {"dbase": ls_dbase, "received": False})())
    monkeypatch.setattr("sys.stdin", iter([""]))

    li_rc = vcw.main()

    assert 0 == li_rc
    assert not (tmp_path / "nao_existe.db").exists()


def test_main_caminho_absoluto_retorna_1_e_nao_toca_no_banco(tmp_path, monkeypatch):
    """
    listagem com caminho absoluto: main() retorna 1 (vol_sync.sh aborta sem
    baixar/remover) e o catalog.db nem é criado
    """
    ls_dbase = str(tmp_path / "nao_existe.db")

    monkeypatch.setattr(vcw, "arg_parse",
                        lambda: type("Args", (), {"dbase": ls_dbase, "received": False})())
    monkeypatch.setattr("sys.stdin", iter([f"42.0|/home/webpca/radar/{MS_PATH}\n"]))

    li_rc = vcw.main()

    assert 1 == li_rc
    assert not (tmp_path / "nao_existe.db").exists()

# < the end >──────────────────────────────────────────────────────────────────────────


# < histórico de recepção (migração 2) >───────────────────────────────────────────────

def _obs(fs_dbase):
    lconn = sqlite3.connect(fs_dbase)

    try:
        return lconn.execute(f"SELECT fullpath, mtime, last_mtime, received_at, resends "
                             f"FROM {ct.CS_TABLE} ORDER BY fullpath").fetchall()

    finally:
        lconn.close()


def test_listagem_nova_nasce_nao_recebida(tmp_path):
    ls_dbase = str(tmp_path / "catalog.db")

    vcw.write_observations(ls_dbase, [(MS_PATH, 10.0, MI_TS)])

    assert [(MS_PATH, 10.0, 10.0, None, 0)] == _obs(ls_dbase)


def test_mark_received_so_o_que_esta_no_sync_dir(tmp_path):
    ls_dbase = str(tmp_path / "catalog.db")
    lpth_sync = tmp_path / "radar"
    (lpth_sync / MS_PATH).parent.mkdir(parents=True)
    (lpth_sync / MS_PATH).write_bytes(b"x")
    vcw.write_observations(ls_dbase, [(MS_PATH, 10.0, MI_TS), ("x/y/falta.mvol", 11.0, None)])

    assert (1, 1) == vcw.mark_received(ls_dbase, [MS_PATH, "x/y/falta.mvol"], lpth_sync)

    ldct = {lt[0]: lt[3] for lt in _obs(ls_dbase)}
    assert ldct[MS_PATH] is not None and ldct["x/y/falta.mvol"] is None

    # de novo: já recebido, não remarca
    assert (0, 1) == vcw.mark_received(ls_dbase, [MS_PATH, "x/y/falta.mvol"], lpth_sync)


def test_reenvio_conta_e_volta_a_nao_recebido(tmp_path):
    ls_dbase = str(tmp_path / "catalog.db")
    lpth_sync = tmp_path / "radar"
    (lpth_sync / MS_PATH).parent.mkdir(parents=True)
    (lpth_sync / MS_PATH).write_bytes(b"x")

    vcw.write_observations(ls_dbase, [(MS_PATH, 10.0, MI_TS)])
    vcw.mark_received(ls_dbase, [MS_PATH], lpth_sync)

    # o mesmo nome de novo no servidor: reenvio
    assert 0 == vcw.write_observations(ls_dbase, [(MS_PATH, 20.0, MI_TS)])
    assert [(MS_PATH, 10.0, 20.0, None, 1)] == _obs(ls_dbase)


def test_nome_que_so_continua_no_servidor_nao_e_reenvio(tmp_path):
    # rsync falhou: o nome aparece de novo na próxima listagem sem ter chegado
    ls_dbase = str(tmp_path / "catalog.db")

    vcw.write_observations(ls_dbase, [(MS_PATH, 10.0, MI_TS)])
    vcw.write_observations(ls_dbase, [(MS_PATH, 10.0, MI_TS)])

    assert [(MS_PATH, 10.0, 10.0, None, 0)] == _obs(ls_dbase)


def test_main_received(tmp_path, monkeypatch):
    ls_dbase = str(tmp_path / "catalog.db")
    lpth_sync = tmp_path / "radar"
    (lpth_sync / MS_PATH).parent.mkdir(parents=True)
    (lpth_sync / MS_PATH).write_bytes(b"x")
    vcw.write_observations(ls_dbase, [(MS_PATH, 10.0, MI_TS)])

    monkeypatch.setattr(vcw, "arg_parse", lambda: type(
        "Args", (), {"dbase": ls_dbase, "received": True, "sync_dir": lpth_sync})())
    monkeypatch.setattr("sys.stdin", iter([f"{MS_PATH}\n", "\n"]))

    assert 0 == vcw.main()
    assert _obs(ls_dbase)[0][3] is not None

    # banco fora da versão: rc 1
    monkeypatch.setattr(vcw, "arg_parse", lambda: type(
        "Args", (), {"dbase": str(tmp_path / "outro.db"), "received": True,
                     "sync_dir": lpth_sync})())
    monkeypatch.setattr("sys.stdin", iter([f"{MS_PATH}\n"]))

    assert 1 == vcw.main()
