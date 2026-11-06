# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

rd_pyart_adapter
conversão de RadarVolume (RainFlow) para pyart.core.Radar — único ponto de
contato com Py-ART

2026.set  mlabru  import apps.ingest.radar_volume (RainFlow) trocado
                  por radar.rd_volume deste repo

2026.may  mlabru  initial version (Linux/Python)
"""
# < imports >──────────────────────────────────────────────────────────────────────────

# python library
from __future__ import annotations

import datetime
import logging

# numPy
import numpy as np

# ARM Py-ART
import pyart

# radar
import radar.rd_volume as rv

# < logging >--------------------------------------------------------------------------

# logger
M_LOG = logging.getLogger(__name__)
M_LOG.setLevel(logging.DEBUG)

# -------------------------------------------------------------------------------------
def _seconds_since(fdt_timestamp: datetime.datetime,
                   fdt_reference: datetime.datetime) -> float:
    """
    retorna diferença temporal em segundos
    """
    # logger
    M_LOG.debug(">> _seconds_since")

    return (fdt_timestamp - fdt_reference).total_seconds()

# -------------------------------------------------------------------------------------
def to_pyart(f_volume: rv.RadarVolume, fs_field_name: str = "DBZH"):
    """
    converte RadarVolume do RainFlow para pyart.Radar.

    cada RadarScan do RainFlow corresponde a um sweep do objeto Radar do
    Py-ART.
    """
    # logger
    M_LOG.debug(">> to_pyart")


    f_volume.validate()

    llst_scans = f_volume.scans

    if not llst_scans:
        # raise an exception
        raise ValueError("RadarVolume não possui scans")

    _validate_range_geometry(llst_scans)

    # número total de raios
    li_nrays = sum(l_scan.n_rays for l_scan in llst_scans)

    # O Py-ART Radar possui uma única dimensão de gates.
    #
    # Como os scans GAMIC podem ter diferentes números
    # de gates, usamos o maior número e preenchemos
    # os restantes com NaN.
    li_ngates = max(l_scan.n_gates for l_scan in llst_scans)

    #>> arrays principais

    l_time = np.zeros(li_nrays, dtype=np.float64)
    l_azimuth = np.zeros(li_nrays, dtype=np.float32)
    l_elevation = np.zeros(li_nrays, dtype=np.float32)
    l_data = np.full((li_nrays, li_ngates), np.nan, dtype=np.float32)
    l_sweep_number = np.zeros(li_nrays, dtype=np.int32)
    l_sweep_start = np.zeros(len(llst_scans), dtype=np.int32)
    l_sweep_end = np.zeros(len(llst_scans), dtype=np.int32)
    l_fixed_angle = np.zeros(len(llst_scans), dtype=np.float32)

    #>> preenchimento dos sweeps

    li_ray_offset = 0

    for li_sweep_index, l_scan in enumerate(llst_scans):

        li_start = li_ray_offset
        li_end = li_ray_offset + l_scan.n_rays - 1

        l_sweep_start[li_sweep_index] = li_start
        l_sweep_end[li_sweep_index] = li_end

        l_fixed_angle[li_sweep_index] = l_scan.elevation

        l_ray_slice = slice(li_start, li_end + 1)

        #>> tempo

        for li_i in range(l_scan.n_rays):

            ldt_timestamp = l_scan.timestamp

            l_time[li_start + li_i] = _seconds_since(ldt_timestamp, f_volume.timestamp)

        #>> geometria

        l_azimuth[l_ray_slice] = l_scan.azimuth.astype(np.float32)

        l_elevation[l_ray_slice] = l_scan.elevation_angles.astype(np.float32)

        #>> dados

        l_data[ li_start : li_end + 1, : l_scan.n_gates ] = l_scan.data

        #>> sweep number

        l_sweep_number[l_ray_slice] = li_sweep_index

        li_ray_offset = li_end + 1

    #>> range

    # Py-ART possui um único vetor de range.  Como os scans podem possuir
    # diferentes números de gates e diferentes range_step, não podemos
    # simplesmente assumir que todos usam o mesmo vetor.
    #
    # para os dados observados:
    # BEL-250: scans iniciais: 240 m
    # BEL-400: aproximadamente 510 m
    #
    # usamos o range do primeiro sweep como referência.  Esta decisão será
    # revisada caso encontremos diferenças internas relevantes.

    l_reference_scan = llst_scans[0]

    l_range_data = l_reference_scan.ranges.astype(np.float32)

    #>> dicionários Py-ART

    ldct_time_dict = { "data": l_time,
                  "units": ( "seconds since "
                            f"{f_volume.timestamp.strftime('%Y-%m-%dT%H:%M:%SZ')}" ),
                  "calendar": "gregorian" }

    ldct_range_dict = { "data": l_range_data,
                   "units": "meters",
                   "long_name": "Range from radar" }

    ldct_latitude_dict = { "data": np.asarray( [f_volume.latitude], dtype=np.float64),
                      "units": "degrees" }

    ldct_longitude_dict = { "data": np.asarray( [f_volume.longitude], dtype=np.float64),
                       "units": "degrees" }

    ldct_altitude_dict = { "data": np.asarray( [f_volume.altitude], dtype=np.float64),
                      "units": "meters" }

    ldct_sweep_number_dict = { "data": np.arange(len(llst_scans), dtype=np.int32) }

    ldct_sweep_mode_dict = { "data": np.asarray(["ppi"] * len(llst_scans)) }

    ldct_fixed_angle_dict = { "data": l_fixed_angle,
                         "units": "degrees" }

    ldct_sweep_start_dict = { "data": l_sweep_start }

    ldct_sweep_end_dict = { "data": l_sweep_end }

    ldct_azimuth_dict = { "data": l_azimuth,
                     "units": "degrees" }

    ldct_elevation_dict = { "data": l_elevation,
                       "units": "degrees" }

    ldct_fields = { fs_field_name: { "data": np.ma.masked_invalid(l_data),
                             "units": "dBZ",
                             "long_name": ("Equivalent reflectivity factor"),
                             "standard_name": ("equivalent_reflectivity_factor") } }

    #>> Py-ART Radar

    l_radar = pyart.core.Radar(
                time=ldct_time_dict,
                _range=ldct_range_dict,
                fields=ldct_fields,
                metadata={ "instrument_name": f_volume.station,
                           "source": "GAMIC MVOL",
                           "product": (f"{f_volume.station}-" f"{f_volume.range_km}") },
                scan_type="ppi",
                latitude=ldct_latitude_dict,
                longitude=ldct_longitude_dict,
                altitude=ldct_altitude_dict,
                sweep_number=ldct_sweep_number_dict,
                sweep_mode=ldct_sweep_mode_dict,
                fixed_angle=ldct_fixed_angle_dict,
                sweep_start_ray_index=ldct_sweep_start_dict,
                sweep_end_ray_index=ldct_sweep_end_dict,
                azimuth=ldct_azimuth_dict,
                elevation=ldct_elevation_dict)

    # ok
    return l_radar

# -------------------------------------------------------------------------------------
def _validate_range_geometry(flst_scans):
    """
    verifica se todos os sweeps são compatíveis com um único eixo de range
    Py-ART
    """
    # logger
    M_LOG.debug(">> _validate_range_geometry")

    l_reference = flst_scans[0]

    lf_ref_start = l_reference.range_start
    lf_ref_step = l_reference.range_step

    for li_index, l_scan in enumerate(flst_scans[1:], start=1):

        if not np.isclose(l_scan.range_start, lf_ref_start, atol=1.0):
            # raise an exception
            raise ValueError("range_start diferente entre sweeps: "
                             f"scan 0={lf_ref_start}, "
                             f"scan {li_index}={l_scan.range_start}")

        if not np.isclose(l_scan.range_step, lf_ref_step, atol=1.0):
            # raise an exception
            raise ValueError("range_step diferente entre sweeps: "
                             f"scan 0={lf_ref_step}, "
                             f"scan {li_index}={l_scan.range_step}")

# < the end >--------------------------------------------------------------------------
