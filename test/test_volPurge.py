# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

test_volPurge
testes unitários de volPurge (retenção dos .mvol): idade pelo horário do
volume, pendentes (view cappi_pending do nowcast ou status daqui), limite de
disco, ausentes, sync-dir e dry-run

2026.set  mlabru  initial version (Linux/Python)
"""
# < imports >──────────────────────────────────────────────────────────────────────────

# python library
import pathlib
import sqlite3
from unittest import mock

# pytest
import pytest

# model
import dbase.vol_dbase as vd
import volPurge as vp

# < helpers >──────────────────────────────────────────────────────────────────────────

# "agora" dos testes e um dia em segundos
MI_NOW = 1_800_000_000
MI_DAY = 86400

# -------------------------------------------------------------------------------------
@pytest.fixture
def env(tmp_path):
    """
    (catalog.db, sync-dir, add) -- add(ts, status, write=True, path=None)
    registra um volume e cria o .mvol no sync-dir
    """
    ls_db = str(tmp_path / "catalog.db")
    lpth_sync = tmp_path / "sync"
    (lpth_sync / "Cangucu" / "250").mkdir(parents=True)

    def _add(fi_ts, fi_status=vd.CI_STATUS_DONE, fb_write=True, fpth=None):
        lpth = fpth or lpth_sync / "Cangucu" / "250" / f"CGU-250--{fi_ts}.mvol"

        if fb_write:
            lpth.parent.mkdir(parents=True, exist_ok=True)
            lpth.write_bytes(b"x")

        with vd.transaction_write(ls_db) as ldb:
            ldb.insert_volume("CGU", 250, fi_ts, str(lpth), 1, None)
            ldb.cursor.execute("UPDATE volumes SET status = ? WHERE timestamp = ?",
                               (fi_status, fi_ts))

        return lpth

    return ls_db, lpth_sync, _add

# -------------------------------------------------------------------------------------
def _has_mvol(fs_db):
    lconn = sqlite3.connect(fs_db)

    try:
        return dict(lconn.execute("SELECT timestamp, has_mvol FROM volumes"))

    finally:
        lconn.close()

# -------------------------------------------------------------------------------------
def _purge(fs_db, fpth_sync, **fdct):
    return vp.purge(fs_db, fpth_sync, fdct.pop("retain", 7), fi_now=MI_NOW, **fdct)

# < retenção >─────────────────────────────────────────────────────────────────────────

def test_apaga_so_os_antigos_ja_convertidos(env):
    ls_db, lpth_sync, add = env
    lpth_old = add(MI_NOW - 8 * MI_DAY)                                 # DONE, 8 d
    lpth_new = add(MI_NOW - 6 * MI_DAY)                                 # DONE, 6 d
    lpth_fail = add(MI_NOW - 9 * MI_DAY, vd.CI_STATUS_FAILED)           # FAILED final
    lpth_pend = add(MI_NOW - 9 * MI_DAY + 1, vd.CI_STATUS_NEW)          # pendente

    lctr = _purge(ls_db, lpth_sync)

    assert 2 == lctr[vp.CS_REMOVED]
    assert not lpth_old.exists() and not lpth_fail.exists()
    assert lpth_new.exists() and lpth_pend.exists()
    assert {MI_NOW - 8 * MI_DAY: 0, MI_NOW - 6 * MI_DAY: 1,
            MI_NOW - 9 * MI_DAY: 0, MI_NOW - 9 * MI_DAY + 1: 1} == _has_mvol(ls_db)

# -------------------------------------------------------------------------------------
def test_pendente_so_sai_pelo_limite_de_disco(env):
    ls_db, lpth_sync, add = env
    lpth_a = add(MI_NOW - 20 * MI_DAY, vd.CI_STATUS_PROCESSING)
    lpth_b = add(MI_NOW - 40 * MI_DAY, vd.CI_STATUS_NEW)

    lctr = _purge(ls_db, lpth_sync, ff_max_days=30)

    assert (1, 1) == (lctr[vp.CS_REMOVED], lctr[vp.CS_FORCED])
    assert lpth_a.exists() and not lpth_b.exists()

# -------------------------------------------------------------------------------------
def test_view_do_nowcast_decide_o_pendente(env):
    ls_db, lpth_sync, add = env
    lpth_done = add(MI_NOW - 8 * MI_DAY)                          # DONE aqui, pendente lá
    lpth_new = add(MI_NOW - 9 * MI_DAY, vd.CI_STATUS_NEW)         # NEW aqui, com produto lá

    # view do nowcast: só o primeiro ainda sem produto final
    lconn = sqlite3.connect(ls_db)
    lconn.execute(f"CREATE VIEW {vd.CS_VIEW_PENDING} AS SELECT radar, alcance, timestamp, "
                  f"fullpath FROM volumes WHERE timestamp = {MI_NOW - 8 * MI_DAY}")
    lconn.commit()
    lconn.close()

    _purge(ls_db, lpth_sync)

    assert lpth_done.exists() and not lpth_new.exists()

# -------------------------------------------------------------------------------------
def test_ausente_so_corrige_has_mvol(env):
    ls_db, lpth_sync, add = env
    add(MI_NOW - 8 * MI_DAY, fb_write=False)

    lctr = _purge(ls_db, lpth_sync)

    assert (0, 1) == (lctr[vp.CS_REMOVED], lctr[vp.CS_MISSING])
    assert {MI_NOW - 8 * MI_DAY: 0} == _has_mvol(ls_db)

# -------------------------------------------------------------------------------------
def test_fora_do_sync_dir_nao_e_apagado(env, tmp_path):
    ls_db, lpth_sync, add = env
    lpth = add(MI_NOW - 8 * MI_DAY, fpth=tmp_path / "outro" / "CGU-250.mvol")

    lctr = _purge(ls_db, lpth_sync)

    assert 1 == lctr[vp.CS_OUTSIDE]
    assert lpth.exists()
    assert {MI_NOW - 8 * MI_DAY: 1} == _has_mvol(ls_db)

# -------------------------------------------------------------------------------------
def test_sinteticos_nao_sao_tocados(env):
    ls_db, lpth_sync, add = env
    lpth = add(MI_NOW - 8 * MI_DAY, vd.CI_STATUS_INTERPOLATED)

    assert 0 == sum(_purge(ls_db, lpth_sync).values())
    assert lpth.exists()

# -------------------------------------------------------------------------------------
def test_dry_run_nao_altera(env):
    ls_db, lpth_sync, add = env
    lpth = add(MI_NOW - 8 * MI_DAY)

    assert 1 == _purge(ls_db, lpth_sync, fb_dry_run=True)[vp.CS_REMOVED]
    assert lpth.exists()
    assert {MI_NOW - 8 * MI_DAY: 1} == _has_mvol(ls_db)

# -------------------------------------------------------------------------------------
def test_erro_ao_apagar_mantem_has_mvol(env):
    ls_db, lpth_sync, add = env
    add(MI_NOW - 8 * MI_DAY)

    with mock.patch.object(pathlib.Path, "unlink", side_effect=PermissionError("ro")):
        lctr = _purge(ls_db, lpth_sync)

    assert 1 == lctr[vp.CS_ERROR]
    assert {MI_NOW - 8 * MI_DAY: 1} == _has_mvol(ls_db)

# < sync-dir >─────────────────────────────────────────────────────────────────────────

def test_sync_dir_vazio_ou_ausente_recusa(env, tmp_path):
    ls_db, _, add = env
    add(MI_NOW - 8 * MI_DAY, fb_write=False)

    (tmp_path / "vazio").mkdir()

    for lpth in (tmp_path / "vazio", tmp_path / "nao_existe"):
        with pytest.raises(RuntimeError):
            _purge(ls_db, lpth)

    # nada foi marcado como ausente
    assert {MI_NOW - 8 * MI_DAY: 1} == _has_mvol(ls_db)

# -------------------------------------------------------------------------------------
def test_main(env, tmp_path):
    ls_db, lpth_sync, _ = env

    assert 0 == vp.main([ls_db, "--sync-dir", str(lpth_sync), "--retain-days", "7"])
    assert 1 == vp.main([ls_db, "--sync-dir", str(tmp_path / "x"), "--retain-days", "7"])

    with pytest.raises(SystemExit):
        vp.main([ls_db, "--sync-dir", str(lpth_sync), "--retain-days", "7", "--max-days", "3"])

# < the end >──────────────────────────────────────────────────────────────────────────
