# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

rd_scan
modelos de dados de um volume de radar (RadarScan, RadarVolume)

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

# < logging >--------------------------------------------------------------------------

# logger
M_LOG = logging.getLogger(__name__)
M_LOG.setLevel(logging.DEBUG)

# < RadarScan >------------------------------------------------------------------------

@dataclasses.dataclass
class RadarScan:
    """
    representa um PPI individual dentro de um volume radar.  Os dados são
    organizados como:

        data[azimuth, gate]

    onde: azimuth -> índice do feixe
          gate    -> índice do gate em distância
    """

    # elevação
    elevation: float
    # timestamp
    timestamp: datetime.datetime

    # azimuth de cada feixe (GAMIC fornece início e fim do setor angular)
    azimuth_start: np.ndarray
    azimuth_stop: np.ndarray

    # elevação de cada feixe
    elevation_start: np.ndarray
    elevation_stop: np.ndarray

    # alcance
    range_start: float
    range_step: float

    # dados
    data: np.ndarray

    # field
    quantity: str = "DBZH"

    # ---------------------------------------------------------------------------------
    def validate(self) -> None:
        """
        valida a consistência interna do scan
        """
        # logger
        M_LOG.debug(">> validate")

        # dimensionalidade
        if 2 != self.data.ndim:
            # raise an exception
            raise ValueError("RadarScan.data deve ser bidimensional")

        # feixes x gates
        li_n_rays, li_n_gates = self.data.shape

        # azimute inicial
        if li_n_rays != len(self.azimuth_start):
            # raise an exception
            raise ValueError("azimuth_start incompatível com data")

        # azimute final
        if li_n_rays != len(self.azimuth_stop):
            # raise an exception
            raise ValueError("azimuth_stop incompatível com data")

        # elevação inicial
        if li_n_rays != len(self.elevation_start):
            # raise an exception
            raise ValueError("elevation_start incompatível com data")

        # elevação final
        if li_n_rays != len(self.elevation_stop):
            # raise an exception
            raise ValueError("elevation_stop incompatível com data")

        # step
        if self.range_step <= 0:
            # raise an exception
            raise ValueError("range_step deve ser positivo")

        # número de feixes 
        if 0 == self.n_rays:
            # raise an exception
            raise ValueError("scan não possui feixes")

        # número de gates
        if 0 == self.n_gates:
            # raise an exception
            raise ValueError("scan não possui gates")

    # ---------------------------------------------------------------------------------
    # properties
    #
    @property
    def azimuth(self) -> np.ndarray:
        """azimute central de cada feixe"""
        return (self.azimuth_start + self.azimuth_stop) / 2.0

    @property
    def elevation_angles(self) -> np.ndarray:
        """elevação central de cada feixe"""
        return (self.elevation_start + self.elevation_stop) / 2.0

    @property
    def max_range(self) -> float:
        """distância aproximada do último gate, em metros"""
        return self.ranges[-1]

    @property
    def n_gates(self) -> int:
        """número de gates de cada feixe"""
        return self.data.shape[1]

    @property
    def n_rays(self) -> int:
        """número de feixes do scan"""
        return self.data.shape[0]

    @property
    def ranges(self) -> np.ndarray:
        """distância central de cada gate, em metros"""
        return (self.range_start + 
                np.arange(self.n_gates, dtype=np.float64) * self.range_step)

# < the end >--------------------------------------------------------------------------
