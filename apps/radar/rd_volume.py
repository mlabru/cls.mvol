# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

rd_volume
modelos de dados de um volume de radar (RadarScan, RadarVolume)

2026.set  mlabru  RadarScan passa a ser importado de radar.rd_scan (só
                  funcionava por causa de 'from __future__ import annotations')

2026.may  mlabru  initial version (Linux/Python)
"""
# < imports >──────────────────────────────────────────────────────────────────────────

# python library
from __future__ import annotations

import dataclasses
import datetime
import logging

# numPy
import numpy as np

# radar
import radar.rd_scan as rs

# < logging >--------------------------------------------------------------------------

# logger
M_LOG = logging.getLogger(__name__)
M_LOG.setLevel(logging.DEBUG)

# < RadarVolume >----------------------------------------------------------------------

@dataclasses.dataclass
class RadarVolume:
    """
    representação interna de um volume radar

    um volume é composto por um conjunto de scans/PPI, normalmente
    correspondentes a diferentes ângulos de elevação
    """
    # estação
    station: str
    # alcance
    range_km: int
    # data e hora
    timestamp: datetime.datetime

    # latitude
    latitude: float
    # longitude
    longitude: float
    # altitude
    altitude: float

    # lista de scans do volume
    scans: list[rs.RadarScan] = dataclasses.field(default_factory=list)

    # ---------------------------------------------------------------------------------
    def get_scan(self, fi_index: int) -> rs.RadarScan:
        """
        retorna um scan pelo índice
        """
        # logger
        M_LOG.debug(">> get_scan")

        # ok
        return self.scans[fi_index]

    # ---------------------------------------------------------------------------------
    def get_scan_by_elevation(self, ff_elevation: float) -> rs.RadarScan:
        """
        retorna o scan cuja elevação é mais próxima da elevação solicitada
        """
        # logger
        M_LOG.debug(">> get_scan_by_elevation")

        if not self.scans:
            # raise an exception
            raise ValueError("volume não possui scans")

        # index
        li_index = int(np.argmin(np.abs(self.elevations - ff_elevation)))

        # ok
        return self.scans[li_index]

    # ---------------------------------------------------------------------------------
    def sort_scans(self) -> None:
        """
        ordena os scans pela elevação
        """
        # logger
        M_LOG.debug(">> sort_scans")

        # ok
        self.scans.sort(key=lambda l_scan: l_scan.elevation)

    # ---------------------------------------------------------------------------------
    def validate(self) -> None:
        """
        valida a consistência do volume
        """
        # logger
        M_LOG.debug(">> validate")

        # estação
        if not self.station:
            # raise an exception
            raise ValueError("station não pode ser vazia")

        # alcance
        if self.range_km not in (250, 400):
            # raise an exception
            raise ValueError("range_km deve ser 250 ou 400")

        # latitude
        if not (-90.0 <= self.latitude <= 90.0):
            # raise an exception
            raise ValueError("latitude inválida")

        # longitude
        if not (-180.0 <= self.longitude <= 180.0):
            # raise an exception
            raise ValueError("longitude inválida")

        # altitude
        if self.altitude < -500:
            # raise an exception
            raise ValueError("altitude inválida")

        # scan list
        if not self.scans:
            # raise an exception
            raise ValueError("volume não possui scans")

        # scan 
        for l_scan in self.scans:
            # validade each scan
            l_scan.validate()

        # validade elevations
        self._validate_elevations()

    # ---------------------------------------------------------------------------------
    def _validate_elevations(self) -> None:
        """
        verifica se as elevações são consistentes
        """
        # logger
        M_LOG.debug(">> _validate_elevations")

        # elevations list
        llst_elevations = self.elevations

        # finitude
        if not np.all(np.isfinite(llst_elevations)):
            # raise an exception
            raise ValueError("volume contém elevações inválidas")

        # lower limit 
        if np.any(llst_elevations < 0.0):
            # raise an exception
            raise ValueError("elevação negativa encontrada")

        # upper limit
        if np.any(llst_elevations > 90.0):
            # raise an exception
            raise ValueError("elevação maior que 90 graus")

        # número de elevações
        if len(llst_elevations) > 1:
            # direrenças entre elevações
            llst_differences = np.diff(llst_elevations)

            if np.any(llst_differences <= 0):
                # raise an exception
                raise ValueError("elevações devem ser estritamente crescentes")

    # ---------------------------------------------------------------------------------
    # properties
    #
    @property
    def elevations(self) -> np.ndarray:
        """elevações dos scans, ordenadas na ordem atual"""
        return np.asarray([l_scan.elevation for l_scan in self.scans], dtype=np.float64)

    @property
    def n_scans(self) -> int:
        """número de scans do volume"""
        return len(self.scans)

# < the end >--------------------------------------------------------------------------
