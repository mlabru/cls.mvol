# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

test_vol_cfg
testes do vol_cfg.sh (carregado pelo vol_sync.sh com VOL_SYNC_NO_MAIN=true):
padrões de produção, override pelo ambiente e trava CLS_ENV=test

2026.nov  mlabru  CLS_LIB obrigatória: sem ela, erro com a causa
2026.nov  mlabru  cls.env (CLS_ENV_FILE) e CLS_LIB; MET_ENV/MET_TST_ROOT (nomes
                  antigos) ainda travam; ambiente limpo também de CLS_*
2026.out  mlabru  ".." não escapa da raiz (cls_check_test_env usa realpath -m)
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
    o ambiente limpo de VOL_*/MET_*/CLS_* herdados (menos CLS_LIB e CLS_PYLIB,
    do conftest) mais fdct_env.  Sem CLS_ENV_FILE em fdct_env, nenhum cls.env é
    carregado; valor None em fdct_env remove a variável
    """
    ldct_env = {ls: lv for ls, lv in os.environ.items()
                if not ls.startswith(("VOL_", "MET_", "CLS_"))}
    ldct_env["CLS_ENV_FILE"] = os.devnull
    ldct_env["CLS_LIB"] = os.environ["CLS_LIB"]
    ldct_env["CLS_PYLIB"] = os.environ["CLS_PYLIB"]
    ldct_env.update(fdct_env or {})
    ldct_env = {ls: lv for ls, lv in ldct_env.items() if lv is not None}

    ls_echo = "; ".join(f'echo "${{{ls}}}"' for ls in CT_VARS)
    ls_cmd = f'VOL_SYNC_NO_MAIN=true; source "{MPTH_ROOT}/vol_sync.sh"; {ls_echo}'

    # ok
    return subprocess.run(["bash", "-c", ls_cmd], capture_output=True, text=True, env=ldct_env)

# -------------------------------------------------------------------------------------
def _tst_env(fpth_root: pathlib.Path, **kwargs) -> dict:
    """
    ambiente de teste coerente (como o tst_env/env.sh), com overrides
    """
    ldct = {"CLS_ENV": "test",
            "CLS_TST_ROOT": str(fpth_root),
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
    del ldct["CLS_TST_ROOT"]

    lproc = _source(ldct)

    assert 0 != lproc.returncode
    assert "CLS_TST_ROOT" in lproc.stderr

def test_prefixo_parecido_nao_passa(tmp_path):
    # <raiz>2/... não está dentro de <raiz>/
    lproc = _source(_tst_env(tmp_path, VOL_PATH=f"{tmp_path}2/mvol"))

    assert 1 == lproc.returncode

def test_trava_recusa_escape_por_dot_dot(tmp_path):
    # <raiz>/../producao casava com o padrão "<raiz>"/* antes do realpath -m
    lproc = _source(_tst_env(tmp_path / "tst", VOL_PATH=str(tmp_path / "tst" / ".." / "producao")))

    assert 1 == lproc.returncode
    assert "fora de" in lproc.stderr

# < cls.env, CLS_LIB e transição met -> cls >──────────────────────────────────────────

def test_cls_env_sobrepoe_os_padroes(tmp_path):
    lpth_env = tmp_path / "cls.env"
    lpth_env.write_text('VOL_PATH="${VOL_PATH:-/srv/cls/mvol}"\n')

    lproc = _source({"USER": "fulano", "CLS_ENV_FILE": str(lpth_env)})

    assert 0 == lproc.returncode, lproc.stderr
    assert "/srv/cls/mvol" == lproc.stdout.splitlines()[1]

def test_ambiente_vence_o_cls_env(tmp_path):
    lpth_env = tmp_path / "cls.env"
    lpth_env.write_text('VOL_PATH="${VOL_PATH:-/srv/cls/mvol}"\n')

    lproc = _source({"CLS_ENV_FILE": str(lpth_env), "VOL_PATH": "/outro/mvol"})

    assert 0 == lproc.returncode, lproc.stderr
    assert "/outro/mvol" == lproc.stdout.splitlines()[1]

def test_banco_compartilhado_vem_do_cls_root(tmp_path):
    # sem VOL_DBASE_FILE, o catalog.db é o da raiz da instalação (cls.env)
    lpth_env = tmp_path / "cls.env"
    lpth_env.write_text('CLS_ROOT="${CLS_ROOT:-/srv/cls.nowcast}"\n'
                        'CLS_DBASE_FILE="${CLS_DBASE_FILE:-${CLS_ROOT}/data/dbase/catalog.db}"\n')

    lproc = _source({"CLS_ENV_FILE": str(lpth_env)})
    assert 0 == lproc.returncode, lproc.stderr
    assert "/srv/cls.nowcast/data/dbase/catalog.db" == lproc.stdout.splitlines()[2]

    # VOL_DBASE_FILE explícito continua vencendo
    lproc = _source({"CLS_ENV_FILE": str(lpth_env), "VOL_DBASE_FILE": "/outro/catalog.db"})
    assert "/outro/catalog.db" == lproc.stdout.splitlines()[2]

def test_cls_lib_do_cls_env_localiza_o_cls_common(tmp_path):
    # cls_common.sh falso: prova que veio de CLS_LIB, não do symlink ao lado
    lpth_lib = tmp_path / "lib"
    lpth_lib.mkdir()
    (lpth_lib / "cls_common.sh").write_text(
        'cls_check_test_env() { echo "cls_common falso" >&2; }\n'
        'cls_log() { :; }\ncheck_log_size() { :; }\ncls_setup_pythonpath() { :; }\n')
    lpth_env = tmp_path / "cls.env"
    lpth_env.write_text(f'CLS_LIB="${{CLS_LIB:-{lpth_lib}}}"\n')

    lproc = _source({"CLS_ENV_FILE": str(lpth_env), "CLS_LIB": None})

    assert 0 == lproc.returncode, lproc.stderr
    assert "cls_common falso" in lproc.stderr

def test_sem_cls_lib_falha_com_a_causa():
    # sem cls.env nem CLS_LIB não há reserva (o symlink saiu no passo 2)
    lproc = _source({"CLS_LIB": None})

    assert 1 == lproc.returncode
    assert "CLS_LIB" in lproc.stderr

def test_sem_cls_pylib_falha_com_a_causa():
    # sem o pacote Python comum, volDBWriter/volScan nem importariam
    lproc = _source({"CLS_PYLIB": None})

    assert 1 == lproc.returncode
    assert "CLS_PYLIB" in lproc.stderr

def test_cls_pylib_vai_para_o_pythonpath():
    lproc = subprocess.run(["bash", "-c", f'VOL_SYNC_NO_MAIN=true; source "{MPTH_ROOT}/vol_sync.sh"; '
                                          'echo "$PYTHONPATH"'],
                           capture_output=True, text=True,
                           env={**os.environ, "CLS_ENV_FILE": os.devnull, "PYTHONPATH": ""})

    assert 0 == lproc.returncode, lproc.stderr
    assert os.environ["CLS_PYLIB"] == lproc.stdout.strip()

def test_met_env_antigo_ainda_trava(tmp_path):
    # um env.sh antigo (MET_*) não pode desligar a trava em silêncio
    ldct = _tst_env(tmp_path, VOL_PATH="/srv/producao/mvol")
    ldct["MET_ENV"] = ldct.pop("CLS_ENV")
    ldct["MET_TST_ROOT"] = ldct.pop("CLS_TST_ROOT")

    lproc = _source(ldct)

    assert 1 == lproc.returncode
    assert "obsoleta" in lproc.stderr
    assert "fora de" in lproc.stderr

# < the end >──────────────────────────────────────────────────────────────────────────
