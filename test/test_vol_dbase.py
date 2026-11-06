# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

test_vol_dbase
testes unitários de vol_dbase (tabela volumes: schema-contrato com o
nowcast, registro, has_mvol e a view de pendentes do nowcast)

2026.set  mlabru  fila/retry/PROCESSING saíram com a conversão (nowcast)
2026.set  mlabru  initial version (Linux/Python)
"""
# < imports >──────────────────────────────────────────────────────────────────────────

# python library
import sqlite3

# model
import dbase.vol_dbase as vd

# < helpers >──────────────────────────────────────────────────────────────────────────

# colunas de volumes em 27.nowcast/04.dvl/apps/work/nwc_database.py (contrato)
MT_VOLUMES_COLUMNS = ("id", "radar", "alcance", "timestamp", "fullpath", "filesize", "sha1",
                      "has_mvol", "has_cappi", "cappi_path", "interpolated", "predicted",
                      "status", "rain_fraction", "valid_fraction", "created_at", "updated_at")

# -------------------------------------------------------------------------------------
def _insert(fs_db, fi_ts=1781530822, fs_radar="CGU"):
    with vd.transaction_write(fs_db) as ldb:
        ldb.insert_volume(fs_radar, 250, fi_ts, f"/x/{fs_radar}-{fi_ts}.mvol", 10, None)

# ─────────────────────────────────────────────────────────────────────────────────────
def test_schema_volumes_igual_ao_do_nowcast(tmp_path):
    ls_db = str(tmp_path / "catalog.db")
    vd.CVolDB(ls_db).close()

    lconn = sqlite3.connect(ls_db)
    lt_cols = tuple(lrow[1] for lrow in lconn.execute("PRAGMA table_info(volumes)"))

    assert MT_VOLUMES_COLUMNS == lt_cols

# -------------------------------------------------------------------------------------
def test_insert_volume_nasce_new_com_mvol(tmp_path):
    ls_db = str(tmp_path / "catalog.db")
    _insert(ls_db)

    with vd.transaction(ls_db) as ldb:
        lrow = ldb.get_volume("CGU", 250, 1781530822)

    assert (vd.CI_STATUS_NEW, 1, 0) == (lrow["status"], lrow["has_mvol"], lrow["has_cappi"])
    # created_at em UTC
    assert lrow["created_at"].endswith("+00:00")

# -------------------------------------------------------------------------------------
def test_update_volume_e_mark_mvol_removed(tmp_path):
    ls_db = str(tmp_path / "catalog.db")
    _insert(ls_db)

    with vd.transaction_write(ls_db) as ldb:
        ldb.mark_mvol_removed("CGU", 250, 1781530822)
        assert 0 == ldb.get_volume("CGU", 250, 1781530822)["has_mvol"]

        # o volScan revê o arquivo: has_mvol volta a 1
        ldb.update_volume("CGU", 250, 1781530822, "/y/CGU.mvol", 20, "abc")
        lrow = ldb.get_volume("CGU", 250, 1781530822)

    assert ("/y/CGU.mvol", 20, "abc", 1) == (lrow["fullpath"], lrow["filesize"], lrow["sha1"],
                                             lrow["has_mvol"])

# -------------------------------------------------------------------------------------
def test_has_pending_view(tmp_path):
    ls_db = str(tmp_path / "catalog.db")

    with vd.transaction(ls_db) as ldb:
        assert not ldb.has_pending_view()

    lconn = sqlite3.connect(ls_db)
    lconn.execute(f"CREATE VIEW {vd.CS_VIEW_PENDING} AS SELECT * FROM volumes")
    lconn.commit()
    lconn.close()

    with vd.transaction(ls_db) as ldb:
        assert ldb.has_pending_view()

# < the end >──────────────────────────────────────────────────────────────────────────
