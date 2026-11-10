# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

test_vol_sync
testes de vol_sync.sh::build_transfer_list (lista de transferência do
rsync: os arquivos da listagem, relativos a REMOTE_DIR) e
list_remote_files (com um ssh falso no PATH), carregando o script com
VOL_SYNC_NO_MAIN=true (sem executar o main)

2026.nov  mlabru  list_remote_files: stderr fora da listagem, find parcial
2026.set  mlabru  listagem já relativa (find %P): build_transfer_list sem prefixo
2026.set  mlabru  sem filtro de idade (não usa mais o relógio do servidor)
2026.set  mlabru  initial version (Linux/Python)
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

# -------------------------------------------------------------------------------------
def _build(fs_listing: str) -> list:
    """
    roda build_transfer_list do vol_sync.sh com a listagem na stdin
    """
    ls_cmd = (f'VOL_SYNC_NO_MAIN=true; source "{MPTH_ROOT}/vol_sync.sh"; '
              f'build_transfer_list')

    lproc = subprocess.run(["bash", "-c", ls_cmd], input=fs_listing, capture_output=True,
                           text=True, check=True)

    return lproc.stdout.splitlines()

# ─────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.skipif(shutil.which("bash") is None or shutil.which("awk") is None,
                    reason="bash/awk indisponíveis")
def test_build_transfer_list_extrai_caminho_e_ignora_malformadas():
    ls_listing = "\n".join([
        "1000|Cangucu/250/CGU-250--2026-06-15--13-40-22.mvol",
        # mtime qualquer (até no futuro): não filtra mais por idade
        "9999999999.5|Belem/400/BEL-400--2026-06-15--13-40-00.mvol",
        # '|' no caminho: só o primeiro separa o mtime
        "1|dir/a|b.mvol",
        # linha vazia / malformada
        "",
        "sem separador",
    ]) + "\n"

    llst = _build(ls_listing)

    assert ["Cangucu/250/CGU-250--2026-06-15--13-40-22.mvol",
            "Belem/400/BEL-400--2026-06-15--13-40-00.mvol",
            "dir/a|b.mvol"] == llst

# -------------------------------------------------------------------------------------
@pytest.mark.skipif(shutil.which("bash") is None or shutil.which("awk") is None,
                    reason="bash/awk indisponíveis")
def test_build_transfer_list_listagem_vazia():
    assert [] == _build("")

# -------------------------------------------------------------------------------------
def _list_remote(ftmp, fs_stdout: str, fs_stderr: str, fi_rc: int):
    """
    roda list_remote_files com um ssh falso que imprime fs_stdout/fs_stderr
    e sai com fi_rc

    :returns: (rc da função, stdout da função, conteúdo de vol_sync.err)
    """
    lpth_bin = ftmp / "bin"
    lpth_bin.mkdir()
    (ftmp / "out.txt").write_text(fs_stdout)
    (ftmp / "err.txt").write_text(fs_stderr)

    lpth_ssh = lpth_bin / "ssh"
    lpth_ssh.write_text(f"#!/bin/bash\ncat '{ftmp}/out.txt'\ncat '{ftmp}/err.txt' >&2\n"
                        f"exit {fi_rc}\n")
    lpth_ssh.chmod(0o755)

    lpth_vol = ftmp / "vol"
    for ls_dir in ("logs", "data/temp"):
        (lpth_vol / ls_dir).mkdir(parents=True)

    ldct_env = {k: v for k, v in os.environ.items() if k != "MET_ENV"}
    ldct_env.update(PATH=f"{lpth_bin}:{os.environ['PATH']}", VOL_PATH=str(lpth_vol),
                    VOL_SYNC_DIR=str(ftmp / "sync"))

    ls_cmd = f'VOL_SYNC_NO_MAIN=true; source "{MPTH_ROOT}/vol_sync.sh"; list_remote_files'

    lproc = subprocess.run(["bash", "-c", ls_cmd], capture_output=True, text=True,
                           env=ldct_env)

    lpth_err = lpth_vol / "logs" / "vol_sync.err"
    ls_err = lpth_err.read_text() if lpth_err.exists() else ""

    return lproc.returncode, lproc.stdout, ls_err

MS_LINE = "1000.5|Cangucu/250/CGU-250--2026-06-15--13-40-22.mvol\n"

# -------------------------------------------------------------------------------------
@pytest.mark.skipif(shutil.which("bash") is None, reason="bash indisponível")
def test_list_remote_stderr_fica_fora_da_listagem(tmp_path):
    li_rc, ls_out, ls_err = _list_remote(tmp_path, MS_LINE, "Warning: Permanently added\n", 0)

    assert 0 == li_rc
    assert MS_LINE == ls_out
    assert "Permanently added" in ls_err

# -------------------------------------------------------------------------------------
@pytest.mark.skipif(shutil.which("bash") is None, reason="bash indisponível")
def test_list_remote_find_parcial_segue_com_o_listado(tmp_path):
    li_rc, ls_out, ls_err = _list_remote(tmp_path, MS_LINE, "find: 'x': Permission denied\n", 1)

    assert 0 == li_rc
    assert MS_LINE == ls_out
    assert "[warn]" in ls_err and "Permission denied" in ls_err

# -------------------------------------------------------------------------------------
@pytest.mark.skipif(shutil.which("bash") is None, reason="bash indisponível")
@pytest.mark.parametrize("fs_stdout, fi_rc", [(MS_LINE, 255), ("", 1)])
def test_list_remote_falha_do_ssh_ou_find_vazio_aborta(tmp_path, fs_stdout, fi_rc):
    li_rc, _, ls_err = _list_remote(tmp_path, fs_stdout, "erro\n", fi_rc)

    assert 0 != li_rc
    assert "[error]" in ls_err

# < the end >──────────────────────────────────────────────────────────────────────────
