# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

test_vol_cfg
testes do vol_cfg.sh (carregado pelo vol_sync.sh com VOL_SYNC_NO_MAIN=true):
padrões de produção, override pelo ambiente e trava MET_ENV=test

2026.out  mlabru  ".." não escapa da raiz (met_check_test_env usa realpath -m)
2026.out  mlabru  initial version (Linux/Python)
"""
# < imports >──────────────────────────────────────────────────────────────────────────

# python library
import os
import pathlib
import shutil
import subprocess

# pytest
import pytest

# < helpers >──────────────────────────────────────────────────────────────────────────

# raiz do projeto (onde está vol_sync.sh)
MPTH_ROOT = pathlib.Path(__file__).resolve().parent.parent

# variáveis exibidas por _source
CT_VARS = ("VOL_SYNC_DIR", "VOL_PATH", "VOL_DBASE_FILE", "VOL_REMOTE_HOST", "VOL_REMOTE_DIR")

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash indisponível")

# -------------------------------------------------------------------------------------
def _source(fdct_env: dict | None = None) -> subprocess.CompletedProcess:
    """
    carrega o vol_sync.sh sem o main e imprime CT_VARS, uma por linha, com
    o ambiente limpo de VOL_*/MET_* herdados mais fdct_env
    """
    ldct_env = {ls: lv for ls, lv in os.environ.items()
                if not ls.startswith(("VOL_", "MET_"))}
    ldct_env.update(fdct_env or {})

    ls_echo = "; ".join(f'echo "${{{ls}}}"' for ls in CT_VARS)
    ls_cmd = f'VOL_SYNC_NO_MAIN=true; source "{MPTH_ROOT}/vol_sync.sh"; {ls_echo}'

    # ok
    return subprocess.run(["bash", "-c", ls_cmd], capture_output=True, text=True, env=ldct_env)

# -------------------------------------------------------------------------------------
def _tst_env(fpth_root: pathlib.Path, **kwargs) -> dict:
    """
    ambiente de teste coerente (como o tst_env/env.sh), com overrides
    """
    ldct = {"MET_ENV": "test",
            "MET_TST_ROOT": str(fpth_root),
            "VOL_SYNC_DIR": str(fpth_root / "radar"),
            "VOL_PATH": str(fpth_root / "mvol"),
            "VOL_DBASE_FILE": str(fpth_root / "mvol" / "data" / "dbase" / "catalog.db"),
            "VOL_REMOTE_USER": "eu",
            "VOL_REMOTE_IP": "localhost",
            "VOL_REMOTE_DIR": str(fpth_root / "inbox")}
    ldct.update(kwargs)

    # ok
    return ldct

# < testes >───────────────────────────────────────────────────────────────────────────

def test_padroes_de_producao():
    lproc = _source({"USER": "fulano"})

    assert 0 == lproc.returncode, lproc.stderr
    assert ["/mnt/usr.L02/fulano/radar",
            "/home/fulano/Public/mvol",
            "/home/fulano/Public/mvol/data/dbase/catalog.db",
            "webpca@172.18.30.153",
            "/home/webpca/radar"] == lproc.stdout.splitlines()

def test_override_pelo_ambiente(tmp_path):
    lproc = _source(_tst_env(tmp_path))

    assert 0 == lproc.returncode, lproc.stderr
    assert [str(tmp_path / "radar"),
            str(tmp_path / "mvol"),
            str(tmp_path / "mvol" / "data" / "dbase" / "catalog.db"),
            "eu@localhost",
            str(tmp_path / "inbox")] == lproc.stdout.splitlines()

def test_trava_recusa_servidor_real(tmp_path):
    lproc = _source(_tst_env(tmp_path, VOL_REMOTE_IP="172.18.30.153"))

    assert 1 == lproc.returncode
    assert "não é localhost" in lproc.stderr
    assert "" == lproc.stdout

def test_trava_recusa_caminho_fora_da_raiz(tmp_path):
    # VOL_SYNC_DIR sem override: cai no padrão de produção
    ldct = _tst_env(tmp_path)
    del ldct["VOL_SYNC_DIR"]

    lproc = _source(ldct)

    assert 1 == lproc.returncode
    assert "fora de" in lproc.stderr

def test_trava_exige_a_raiz(tmp_path):
    ldct = _tst_env(tmp_path)
    del ldct["MET_TST_ROOT"]

    lproc = _source(ldct)

    assert 0 != lproc.returncode
    assert "MET_TST_ROOT" in lproc.stderr

def test_prefixo_parecido_nao_passa(tmp_path):
    # <raiz>2/... não está dentro de <raiz>/
    lproc = _source(_tst_env(tmp_path, VOL_PATH=f"{tmp_path}2/mvol"))

    assert 1 == lproc.returncode

def test_trava_recusa_escape_por_dot_dot(tmp_path):
    # <raiz>/../producao casava com o padrão "<raiz>"/* antes do realpath -m
    lproc = _source(_tst_env(tmp_path / "tst", VOL_PATH=str(tmp_path / "tst" / ".." / "producao")))

    assert 1 == lproc.returncode
    assert "fora de" in lproc.stderr

# < the end >──────────────────────────────────────────────────────────────────────────
