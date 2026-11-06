# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

rd_gamic_reader
leitura de volumes GAMIC HDF5 (GamicReader)

2026.set  mlabru  imports apps.ingest.*/apps.domain.* (RainFlow)
                  trocados por radar.rd_*/vol_product_key deste repo

2026.may  mlabru  initial version (Linux/Python)
"""
# < imports >──────────────────────────────────────────────────────────────────────────

# python library
from __future__ import annotations

import dataclasses
import datetime
import logging
import pathlib
import re

# numPy
import numpy as np

# h5py
import h5py

# radar
import radar.rd_mvol as mv
import radar.rd_scan as rs
import radar.rd_volume as rv

# locals
import dbase.vol_product_key as pk

# < logging >--------------------------------------------------------------------------

# logger
M_LOG = logging.getLogger(__name__)
M_LOG.setLevel(logging.DEBUG)

# < GamicReader >----------------------------------------------------------------------

@dataclasses.dataclass
class GamicReader:
    """
    leitor de volumes GAMIC MVOL
    """
    # filename
    filename: str | pathlib.Path
    # field
    quantity: str = "DBZH"

    # ---------------------------------------------------------------------------------
    def __post_init__(self) -> None:
        """
        __post_init__
        """
        # logger
        M_LOG.debug(">> __post_init__")

        # filename
        self.filename = pathlib.Path(self.filename)

    # ---------------------------------------------------------------------------------
    def read(self) -> rv.RadarVolume:
        """
        read MVOL file
        """
        # logger
        M_LOG.debug(">> read")

        # parse mvol filename
        l_mvol = mv.parse_mvol(self.filename)

        # open mvol file
        with h5py.File(self.filename, "r") as lfh_h5:
            # read mvol volume
            l_volume = self._read_volume(lfh_h5, l_mvol)

        # sort mvol svans
        l_volume.sort_scans()
        # validade volume
        l_volume.validate()

        # ok
        return l_volume

    # ---------------------------------------------------------------------------------
    def _read_scan(self, f_group: h5py.Group,
                         fdt_volume_timestamp: datetime.datetime) -> rs.RadarScan:
        """
        read scan
        """
        # logger
        M_LOG.debug(">> _read_scan")

        # location
        l_where = f_group["where"]
        # feixe
        l_ray_header = f_group["ray_header"]

        # converte elevação 
        lf_elevation = mv._attr_float(l_where, "elangle")

        if lf_elevation is None:
            # converte elevação
            lf_elevation = mv._attr_float(f_group, "fixed_angle")

        if lf_elevation is None:
            # raise an exception
            raise ValueError(f"Elevação não encontrada em {f_group.name}")

        # azimute
        l_azimuth_start = l_ray_header["azimuth_start"][...]
        l_azimuth_stop = l_ray_header["azimuth_stop"][...]

        # elevação
        l_elevation_start = l_ray_header["elevation_start"][...]
        l_elevation_stop = l_ray_header["elevation_stop"][...]

        # momento
        l_moment = mv._find_moment(f_group, self.quantity)

        # dynamic range
        lf_dyn_min = mv._attr_float(l_moment, "dyn_range_min", -32.0)
        lf_dyn_max = mv._attr_float(l_moment, "dyn_range_max", 95.5)

        # dados
        l_data = mv._decode_moment(l_moment, ff_dyn_range_min=lf_dyn_min, ff_dyn_range_max=lf_dyn_max)

        # alcance
        lf_range_start = mv._attr_float(l_where, "rstart", 0.0)
        lf_range_step = mv._attr_float(l_where, "rscale")

        if lf_range_step is None:
            # range step
            lf_range_step = mv._attr_float(l_where, "range_step")

        if lf_range_step is None:
            # raise an exception
            raise ValueError(f"Resolução de range não encontrada em " f"{f_group.name}")

        # data e hora
        ldt_timestamp = mv._decode_time(f_group) or fdt_volume_timestamp

        # ok
        return rs.RadarScan(
                   elevation=float(lf_elevation),
                   timestamp=ldt_timestamp,
                   azimuth_start=np.asarray(l_azimuth_start, dtype=np.float64),
                   azimuth_stop=np.asarray(l_azimuth_stop, dtype=np.float64),
                   elevation_start=np.asarray(l_elevation_start, dtype=np.float64),
                   elevation_stop=np.asarray(l_elevation_stop, dtype=np.float64),
                   range_start=float(lf_range_start),
                   range_step=float(lf_range_step),
                   data=l_data,
                   quantity=self.quantity)

    # ---------------------------------------------------------------------------------
    def _read_volume(self, f_h5: h5py.File, f_mvol: mv.MvolFile) -> rv.RadarVolume:
        """
        read volume
        """
        # logger
        M_LOG.debug(">> _read_volume")

        # location data         
        l_where = f_h5["where"]

        # converted latitude
        lf_latitude = mv._attr_float(l_where, "lat")

        if lf_latitude is None:
            # raise an exception
            raise ValueError("latitude do radar não encontrada")

        # converted longitude
        lf_longitude = mv._attr_float(l_where, "lon")

        if lf_longitude is None:
            # raise an exception
            raise ValueError("longitude do radar não encontrada")

        # converted altitude
        lf_altitude = mv._attr_float(l_where, "height")

        if lf_altitude is None:
            # raise an exception
            raise ValueError("altitude do radar não encontrada")

        # scans list
        llst_scans: list[rs.RadarScan] = []

        # scan names
        llst_scan_names = sorted(ls_name for ls_name in f_h5
                                         if ls_name.startswith("scan") and
                                            isinstance(f_h5[ls_name], h5py.Group))

        # for names in list...
        for ls_name in llst_scan_names:
            # read scan
            l_scan = self._read_scan(f_h5[ls_name], f_mvol.timestamp)
            # save on list
            llst_scans.append(l_scan)

        # ok
        return rv.RadarVolume(station=f_mvol.product.station,
                              range_km=f_mvol.product.range_km,
                              timestamp=f_mvol.timestamp,
                              latitude=lf_latitude,
                              longitude=lf_longitude,
                              altitude=lf_altitude,
                              scans=llst_scans)

# < the end >--------------------------------------------------------------------------
