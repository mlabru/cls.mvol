# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

rd_mvol
parsing de nomes de arquivo .mvol (sem h5py/numpy: é importado pelos
scripts de cron só para ler o nome)

2026.nov  mlabru  - decodificação HDF5 movida para rd_gamic_reader, único
                    usuário; fix da anotação MvolFile.timestamp
                    (datetime.datetime, não o módulo)

2026.set  mlabru  - import apps.domain.product_key trocado por
                    vol_product_key deste repo
                  - _decode_uv8: expressão quebrada em duas linhas sem
                    parênteses (SyntaxError, módulo não importava)

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

# locals
import dbase.vol_product_key as pk

# < logging >--------------------------------------------------------------------------

# logger
M_LOG = logging.getLogger(__name__)
M_LOG.setLevel(logging.WARNING)

# < constants >------------------------------------------------------------------------

MVOL_PATTERN = re.compile(
    r"^"
    r"(?P<station>[A-Za-z]{3})"
    r"-"
    r"(?P<range>\d+)"
    r"--"
    r"(?P<year>\d{4})"
    r"-"
    r"(?P<month>\d{2})"
    r"-"
    r"(?P<day>\d{2})"
    r"--"
    r"(?P<hour>\d{2})"
    r"-"
    r"(?P<minute>\d{2})"
    r"-"
    r"(?P<second>\d{2})"
    r"(?:\(\d+\))?"
    r"\.mvol"
    r"$",
    re.IGNORECASE,
)

# < MvolFile >-------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class MvolFile:
    """
    um arquivo .mvol identificado: caminho, produto (station+range) e timestamp real
    """
    # path name
    path: pathlib.Path
    # station + range
    product: pk.ProductKey
    # timestamp
    timestamp: datetime.datetime

# -------------------------------------------------------------------------------------
def parse_mvol(fpth_path: str | pathlib.Path) -> MvolFile:
    """
    parse mvol
    """
    # logger
    M_LOG.debug(">> parse_mvol")

    # converte para Path
    fpth_path = pathlib.Path(fpth_path)

    # pattern match do filename
    l_match = MVOL_PATTERN.match(fpth_path.name)

    if l_match is None:
        # raise an exception
        raise ValueError(f"nome de arquivo inválido: {fpth_path.name}")

    # estação
    ls_station = l_match.group("station").upper()

    # alcance
    li_range_km = int(l_match.group("range"))

    if li_range_km not in (250, 400):
        # raise an exception
        raise ValueError(f"alcance inválido: {li_range_km}. Esperado 250 ou 400 km.")

    # data e hora
    ldt_timestamp = datetime.datetime(int(l_match.group("year")),
                                      int(l_match.group("month")),
                                      int(l_match.group("day")),
                                      int(l_match.group("hour")),
                                      int(l_match.group("minute")),
                                      int(l_match.group("second")),
                                      tzinfo=datetime.timezone.utc)
    # ok
    return MvolFile(path=fpth_path,
                    product=pk.ProductKey(ls_station, li_range_km),
                    timestamp=ldt_timestamp)

# < the end >--------------------------------------------------------------------------
