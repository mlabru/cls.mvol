# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

test_rd_gamic_reader
testes da decodificação GAMIC (UV8) e do GamicReader, sobre um HDF5
mínimo gerado aqui -- só os atributos/datasets que o leitor lê

2026.nov  mlabru  initial version (Linux/Python)
"""
# < imports >──────────────────────────────────────────────────────────────────────────

# python library
import os
import pathlib
import subprocess
import sys

# numPy
import numpy as np

# pytest
import pytest

h5py = pytest.importorskip("h5py")

# model
import radar.rd_gamic_reader as gr

# apps/ (o subprocess precisa dele no PYTHONPATH)
MPTH_APPS = pathlib.Path(__file__).resolve().parent.parent / "apps"

# < helpers >──────────────────────────────────────────────────────────────────────────

# 2 raios x 3 gates: 0 = sem dado, 255 = dyn_range_max
MT_RAW = np.array([[0, 1, 128], [255, 0, 64]], dtype=np.uint8)

# -------------------------------------------------------------------------------------
def _write_mvol(fpth_file):
    """
    grava um .mvol no layout GAMIC real (como 03.dat/lmc15.ori): metadados do
    scan em scan<N>/how, ray_header composto, moment_<N> como Dataset UV8.
    2 scans gravados fora de ordem de elevação; o feixe 0 cruza o norte
    """
    lt_ray = np.dtype([("azimuth_start", "<f8"), ("azimuth_stop", "<f8"),
                       ("elevation_start", "<f8"), ("elevation_stop", "<f8")])

    with h5py.File(fpth_file, "w") as lfh:
        lwhere = lfh.create_group("where")
        lwhere.attrs["lat"] = -29.2
        lwhere.attrs["lon"] = -54.9
        lwhere.attrs["height"] = 430.0

        for li_scan, lf_elev in ((0, 1.5), (1, 0.5)):
            lscan = lfh.create_group(f"scan{li_scan}")

            lhow = lscan.create_group("how")
            lhow.attrs["elevation"] = lf_elev
            lhow.attrs["range_start"] = 0.0
            lhow.attrs["range_step"] = 250.0
            lhow.attrs["range_samples"] = 2
            lhow.attrs["timestamp"] = "2026-06-15T13:40:22.500Z"

            lray = np.zeros(2, dtype=lt_ray)
            lray["azimuth_start"] = [359.0, 1.0]
            lray["azimuth_stop"] = [1.0, 2.0]
            lray["elevation_start"] = lf_elev
            lray["elevation_stop"] = lf_elev
            lscan["ray_header"] = lray

            lmoment = lscan.create_dataset("moment_0", data=MT_RAW)
            lmoment.attrs["moment"] = "Z"
            lmoment.attrs["format"] = "UV8"
            lmoment.attrs["dyn_range_min"] = -32.0
            lmoment.attrs["dyn_range_max"] = 95.5

# ─────────────────────────────────────────────────────────────────────────────────────
def test_decode_uv8_escala_e_nodata():
    """
    mesma escala do Py-ART (min + raw/255 * (max - min)); raw 0 vira NaN
    """
    l_out = gr._decode_uv8(MT_RAW, -32.0, 95.5, gr.MI_UV8_NODATA)

    assert np.float32 == l_out.dtype
    assert np.isnan(l_out[0, 0]) and np.isnan(l_out[1, 1])
    assert l_out[1, 0] == pytest.approx(95.5)
    assert l_out[0, 1] == pytest.approx(-32.0 + 127.5 / 255.0)

# -------------------------------------------------------------------------------------
def test_reader_mascara_gates_sem_dado(tmp_path):
    """
    GamicReader: gate com raw 0 não pode virar -32 dBZ (eco válido)
    """
    lpth_file = tmp_path / "CGU-250--2026-06-15--13-40-22.mvol"
    _write_mvol(lpth_file)

    l_volume = gr.GamicReader(lpth_file, quantity="Z").read()
    l_data = l_volume.scans[0].data

    assert 2 == int(np.isnan(l_data).sum())
    assert np.nanmin(l_data) > -32.0

# -------------------------------------------------------------------------------------
def test_reader_layout_gamic_real(tmp_path):
    """
    how.elevation/range_start/range_step * range_samples/timestamp, momento
    como Dataset; scans ordenados por elevação; azimute médio circular
    """
    lpth_file = tmp_path / "STI-250--2026-06-15--13-40-22.mvol"
    _write_mvol(lpth_file)

    l_volume = gr.GamicReader(lpth_file, quantity="DBZH").read()

    assert [0.5, 1.5] == [l_scan.elevation for l_scan in l_volume.scans]

    l_scan = l_volume.scans[0]

    # passo efetivo = range_step * range_samples (como o Py-ART)
    assert 500.0 == l_scan.range_step
    assert 13 == l_scan.timestamp.hour and l_scan.timestamp.tzinfo is not None
    # 359 -> 1 cruza o norte: 0, não 180
    assert l_scan.azimuth[0] == pytest.approx(0.0, abs=1e-6)
    assert l_scan.azimuth[1] == pytest.approx(1.5)

# -------------------------------------------------------------------------------------
def test_rd_mvol_nao_importa_h5py():
    """
    o parser de nome (usado pelos scripts de cron) não depende de h5py/numpy
    -- confere num processo novo, sem os módulos que a suíte já importou
    """
    ls_code = ("import sys, radar.rd_mvol; "
               "sys.exit(int('h5py' in sys.modules or 'numpy' in sys.modules))")

    lproc = subprocess.run([sys.executable, "-c", ls_code], cwd=MPTH_APPS,
                           env={**os.environ, "PYTHONPATH": str(MPTH_APPS)})

    assert 0 == lproc.returncode

# < the end >──────────────────────────────────────────────────────────────────────────
