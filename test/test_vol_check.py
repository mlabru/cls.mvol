# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

test_vol_check
falhas visíveis: códigos de saída do vol_sync.sh e do vol_register.sh,
heartbeats de sucesso (cls_heartbeat) e o verificador vol_check.sh.

os scripts são carregados com <PFX>_NO_MAIN=true e as etapas externas
(ssh, rsync, Python) trocadas por funções falsas, então o main roda de
verdade sem rede nem banco.  Tudo em <tmp> (VOL_PATH, VOL_SYNC_DIR)

2026.nov  mlabru  vol_sync.sh: passo de recepção (mark_received)
2026.nov  mlabru  initial version (Linux/Python)
"""
# < imports >──────────────────────────────────────────────────────────────────────────

# python library
import os
import pathlib
import shutil
import sqlite3
import subprocess
import time

# pytest
import pytest

# < helpers >──────────────────────────────────────────────────────────────────────────

# raiz do projeto
MPTH_ROOT = pathlib.Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash indisponível")

# -------------------------------------------------------------------------------------
def _env(fpth_tmp: pathlib.Path, **kwargs) -> dict:
    """
    ambiente com VOL_* em <tmp> (sem herdar os do shell) e o PATH com um
    diretório de executáveis falsos na frente
    """
    ldct = {ls: lv for ls, lv in os.environ.items() if not ls.startswith(("VOL_", "MET_"))}
    ldct.update({"VOL_PATH": str(fpth_tmp / "mvol"),
                 "VOL_SYNC_DIR": str(fpth_tmp / "radar"),
                 "VOL_DBASE_FILE": str(fpth_tmp / "catalog.db"),
                 "PATH": f"{fpth_tmp / 'bin'}:{os.environ['PATH']}"})
    ldct.update(kwargs)
    (fpth_tmp / "bin").mkdir(exist_ok=True)

    # ok
    return ldct

def _bash(fpth_tmp, fs_script: str, fs_body: str, **kwargs) -> subprocess.CompletedProcess:
    """
    carrega <script>.sh sem o main e roda fs_body (num subshell, para um
    exit do main não encerrar o bash; o rc é capturado com "|| li=$?" porque os
    scripts ligam set -e)
    """
    ls_flag = {"vol_sync": "VOL_SYNC_NO_MAIN", "vol_register": "VOL_REGISTER_NO_MAIN",
               "vol_check": "VOL_CHECK_NO_MAIN"}[fs_script]
    ls_cmd = f'{ls_flag}=true; source "{MPTH_ROOT}/{fs_script}.sh"; {fs_body}'

    # ok
    return subprocess.run(["bash", "-c", ls_cmd], capture_output=True, text=True,
                          env=_env(fpth_tmp, **kwargs))

def _ok_file(fpth_tmp, fs_name: str) -> pathlib.Path:
    return fpth_tmp / "mvol" / "data" / "state" / f"{fs_name}.ok"

def _fake_rsync(fpth_tmp, fi_rc: int) -> None:
    lpth = fpth_tmp / "bin" / "rsync"
    lpth.parent.mkdir(exist_ok=True)
    lpth.write_text(f"#!/bin/sh\necho 'rsync falso rc={fi_rc}'\nexit {fi_rc}\n")
    lpth.chmod(0o755)

# < vol_sync.sh: sync_files >──────────────────────────────────────────────────────────

@pytest.mark.parametrize("fi_rsync_rc, fi_rc, fs_level", [(0, 0, None), (24, 0, "[warn]"),
                                                         (12, 1, "[error]"), (23, 1, "[error]")])
def test_sync_files_rc_do_rsync(tmp_path, fi_rsync_rc, fi_rc, fs_level):
    # 24 = arquivo sumiu na origem: só aviso; outros != 0: falha
    _env(tmp_path)
    _fake_rsync(tmp_path, fi_rsync_rc)

    lproc = _bash(tmp_path, "vol_sync",
                  'ensure_directories; : > "${VOL_TEMP}/lista"; '
                  'li=0; sync_files "${VOL_TEMP}/lista" || li=$?; echo "rc=${li}"')

    assert f"rc={fi_rc}" in lproc.stdout, lproc.stderr

    lpth_err = tmp_path / "mvol" / "logs" / "vol_sync.err"
    if fs_level:
        assert fs_level in lpth_err.read_text()
    else:
        assert not lpth_err.exists() or "rsync" not in lpth_err.read_text()

# < vol_sync.sh: main >────────────────────────────────────────────────────────────────

# etapas externas falsas: listagem com um arquivo, gravação no banco ok
MS_SYNC_STUBS = ('list_remote_files() { echo "1|Cangucu/250/x.mvol"; }; '
                 'persist_listing() { return 0; }; '
                 'mark_received() { echo "marcou $(cat "$1")"; return 0; }; ')

def test_sync_bem_sucedido_grava_heartbeat(tmp_path):
    lproc = _bash(tmp_path, "vol_sync",
                  MS_SYNC_STUBS + 'sync_files() { return 0; }; li=0; (main) || li=$?; echo "rc=${li}"')

    assert "rc=0" in lproc.stdout, lproc.stderr
    assert _ok_file(tmp_path, "vol_sync").read_text().split()[0].isdigit()

def test_sync_com_falha_do_rsync_sai_1_sem_heartbeat(tmp_path):
    lproc = _bash(tmp_path, "vol_sync",
                  MS_SYNC_STUBS + 'sync_files() { return 1; }; li=0; (main) || li=$?; echo "rc=${li}"')

    assert "rc=1" in lproc.stdout
    assert not _ok_file(tmp_path, "vol_sync").exists()

def test_sync_servidor_vazio_e_sucesso(tmp_path):
    lproc = _bash(tmp_path, "vol_sync",
                  'list_remote_files() { :; }; li=0; (main) || li=$?; echo "rc=${li}"')

    assert "rc=0" in lproc.stdout, lproc.stderr
    assert _ok_file(tmp_path, "vol_sync").exists()

def test_sync_falha_no_banco_sai_1_sem_heartbeat(tmp_path):
    lproc = _bash(tmp_path, "vol_sync",
                  'list_remote_files() { echo "1|a/b.mvol"; }; persist_listing() { return 1; }; '
                  'li=0; (main) || li=$?; echo "rc=${li}"')

    assert "rc=1" in lproc.stdout
    assert not _ok_file(tmp_path, "vol_sync").exists()

def test_sync_marca_recepcao_mesmo_com_falha_do_rsync(tmp_path):
    # falha parcial: o que veio fica marcado; rc 1 do mesmo jeito
    lproc = _bash(tmp_path, "vol_sync",
                  MS_SYNC_STUBS + 'sync_files() { return 1; }; li=0; (main) || li=$?; echo "rc=${li}"')

    assert "marcou Cangucu/250/x.mvol" in lproc.stdout
    assert "rc=1" in lproc.stdout

def test_sync_falha_ao_marcar_recepcao_sai_1_sem_heartbeat(tmp_path):
    lproc = _bash(tmp_path, "vol_sync",
                  MS_SYNC_STUBS + 'mark_received() { return 1; }; sync_files() { return 0; }; '
                  'li=0; (main) || li=$?; echo "rc=${li}"')

    assert "rc=1" in lproc.stdout
    assert not _ok_file(tmp_path, "vol_sync").exists()

def test_sync_mark_received_real_grava_no_banco(tmp_path):
    # sem stub: o mark_received chama o volDBWriter --received de verdade
    (tmp_path / "radar" / "Cangucu" / "250").mkdir(parents=True)
    (tmp_path / "radar" / "Cangucu" / "250" / "CGU-250--2026-06-15--13-40-22.mvol").write_bytes(b"x")
    lproc = _bash(tmp_path, "vol_sync",
                  'list_remote_files() { echo "1|Cangucu/250/CGU-250--2026-06-15--13-40-22.mvol"; }; '
                  'sync_files() { return 0; }; li=0; (main) || li=$?; echo "rc=${li}"')

    assert "rc=0" in lproc.stdout, lproc.stderr
    lconn = sqlite3.connect(tmp_path / "catalog.db")
    assert [(1,)] == lconn.execute("SELECT received_at IS NOT NULL FROM vol_raw_observations").fetchall()
    lconn.close()

# < vol_register.sh: main >────────────────────────────────────────────────────────────

@pytest.mark.parametrize("fi_scan, fi_purge, fi_rc, fb_ok", [(0, 0, 0, True),
                                                             (0, 3, 3, False),
                                                             (1, 0, 1, False)])
def test_register_rc_e_heartbeat(tmp_path, fi_scan, fi_purge, fi_rc, fb_ok):
    # falha do volPurge sai com o rc dele (antes só avisava, rc 0)
    lproc = _bash(tmp_path, "vol_register",
                  f'run_scan() {{ return {fi_scan}; }}; run_purge() {{ return {fi_purge}; }}; '
                  'li=0; (main) || li=$?; echo "rc=${li}"', VOL_RETAIN_DAYS="7")

    assert f"rc={fi_rc}" in lproc.stdout, lproc.stderr
    assert fb_ok == _ok_file(tmp_path, "vol_register").exists()

def test_register_sem_retencao_tambem_grava_heartbeat(tmp_path):
    lproc = _bash(tmp_path, "vol_register",
                  'run_scan() { return 0; }; run_purge() { exit 99; }; li=0; (main) || li=$?; echo "rc=${li}"',
                  VOL_RETAIN_DAYS="")

    assert "rc=0" in lproc.stdout, lproc.stderr
    assert _ok_file(tmp_path, "vol_register").exists()

# < vol_check.sh >─────────────────────────────────────────────────────────────────────

def _heartbeat(fpth_tmp, fs_name: str, fi_age_s: int) -> None:
    lpth = _ok_file(fpth_tmp, fs_name)
    lpth.parent.mkdir(parents=True, exist_ok=True)
    lpth.write_text(f"{int(time.time()) - fi_age_s} 2026-11-17T00:00:00Z\n")

def _check(fpth_tmp, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(MPTH_ROOT / "vol_check.sh")], capture_output=True,
                          text=True, env=_env(fpth_tmp, **kwargs))

def test_check_sem_heartbeat_e_unknown(tmp_path):
    lproc = _check(tmp_path)

    assert 3 == lproc.returncode
    assert lproc.stdout.startswith("UNKNOWN:")

def test_check_recentes_e_ok(tmp_path):
    _heartbeat(tmp_path, "vol_sync", 60)
    _heartbeat(tmp_path, "vol_register", 60)

    lproc = _check(tmp_path)

    assert 0 == lproc.returncode, lproc.stdout + lproc.stderr
    assert lproc.stdout.startswith("OK: vol_sync ok há 1 min; vol_register ok há 1 min")

def test_check_atrasado_e_critical_e_vence_unknown(tmp_path):
    _heartbeat(tmp_path, "vol_sync", 31 * 60)    # limite 30 min

    lproc = _check(tmp_path)

    assert 2 == lproc.returncode
    assert lproc.stdout.startswith("CRITICAL:")
    assert "vol_sync sem sucesso há 31 min (máx 30" in lproc.stdout

def test_check_limite_configuravel(tmp_path):
    _heartbeat(tmp_path, "vol_sync", 31 * 60)
    _heartbeat(tmp_path, "vol_register", 60)

    assert 0 == _check(tmp_path, VOL_CHECK_MAX_AGE_MIN="60").returncode

def test_check_heartbeat_ilegivel_e_unknown(tmp_path):
    _heartbeat(tmp_path, "vol_register", 60)
    lpth = _ok_file(tmp_path, "vol_sync")
    lpth.write_text("lixo\n")

    lproc = _check(tmp_path)

    assert 3 == lproc.returncode
    assert "vol_sync sem heartbeat" in lproc.stdout

# < the end >──────────────────────────────────────────────────────────────────────────
