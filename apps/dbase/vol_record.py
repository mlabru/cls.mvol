# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo
    
vol_record
representa um arquivo .mvol identificado no sistema
                
2026.set  mlabru  import apps.domain.product_key (RainFlow) trocado
                  por vol_product_key deste repo

2026.aug  mlabru  initial version (Linux/Python)
"""
# < imports >──────────────────────────────────────────────────────────────────────────
        
# python library
from __future__ import annotations
    
import dataclasses
import datetime
import logging
import pathlib
        
# locals
import dbase.vol_product_key as pk
        
# < logging >--------------------------------------------------------------------------
        
# logger
M_LOG = logging.getLogger(__name__)
M_LOG.setLevel(logging.DEBUG)

# < VolumeRecord >---------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class VolumeRecord:
    """
    representa um arquivo .mvol identificado no sistema
    """

    # radar + alcance
    product: pk.ProductKey
    # timestamp real obtido do nome do arquivo
    timestamp: datetime.datetime
    # caminho do arquivo
    filename: pathlib.Path

    # ---------------------------------------------------------------------------------
    def __post_init__(self) -> None:
        """
        post init
        """
        # logger
        M_LOG.debug(">> __post_init__")

        if self.timestamp.tzinfo is None:
            # raise an exception
            raise ValueError("timestamp deve possuir timezone")

        if self.timestamp.utcoffset() is None:
            # raise an exception
            raise ValueError("timestamp deve possuir UTC offset")

        if not isinstance(self.filename, pathlib.Path):
            # save filename
            object.__setattr__(self, "filename", pathlib.Path(self.filename))

    # ---------------------------------------------------------------------------------
    # properties
    #
    @property
    def timestamp_utc(self) -> datetime.datetime:
        """
        timestamp convertido para UTC
        """
        return self.timestamp.astimezone(datetime.timezone.utc)

# < the end >--------------------------------------------------------------------------
