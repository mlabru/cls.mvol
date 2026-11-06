# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

vol_product_key
identifica univocamente uma série temporal

2026.aug  mlabru  initial version (Linux/Python)
"""
# < imports >──────────────────────────────────────────────────────────────────────────

# python library
from __future__ import annotations

import dataclasses
import logging

# < logging >--------------------------------------------------------------------------

# logger
M_LOG = logging.getLogger(__name__)
M_LOG.setLevel(logging.WARNING)

# < ProductKey >-----------------------------------------------------------------------

@dataclasses.dataclass(frozen=True, order=True)
class ProductKey:
    """
    identifica univocamente uma série temporal de radar
    exemplos: BEL-250
              BEL-400
              CGU-250
              CGU-400
    """
    # station
    station: str
    # range
    range_km: int

    # ---------------------------------------------------------------------------------
    def __post_init__(self) -> None:
        """
        post init
        """
        # logger
        M_LOG.debug(">> __post_init__")

        # convert to uppercase
        ls_station = self.station.upper()

        # check length
        if len(ls_station) != 3:
            # raise an exception
            raise ValueError(f"estação deve possuir 3 letras: {self.station!r}")

        # check is alpha
        if not ls_station.isalpha():
            # raise an exception
            raise ValueError(f"estação inválida: {self.station!r}")

        # check alcance
        if self.range_km not in (250, 400):
            # raise an exception
            raise ValueError(f"alcance não suportado: {self.range_km}")

        # save station
        object.__setattr__(self, "station", ls_station)

    # ---------------------------------------------------------------------------------
    def __str__(self) -> str:
        # logger
        M_LOG.debug(">> __str__")

        # ok
        return f"{self.station}-{self.range_km}"

# < the end >--------------------------------------------------------------------------
