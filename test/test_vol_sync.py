# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

test_vol_sync
testes de vol_sync.sh::build_transfer_list (lista de transferência do
rsync: os arquivos da listagem, relativos a REMOTE_DIR), carregando o
script com VOL_SYNC_NO_MAIN=true (sem executar o main)

2026.set  mlabru  listagem já relativa (find %P): build_transfer_list sem prefixo
2026.set  mlabru  sem filtro de idade (não usa mais o relógio do servidor)
2026.set  mlabru  initial version (Linux/Python)
"""
# < imports >──────────────────────────────────────────────────────────────────────────

# python library
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

# < the end >──────────────────────────────────────────────────────────────────────────
