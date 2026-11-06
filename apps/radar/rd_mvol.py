# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

rd_mvol
parsing de nomes de arquivo .mvol

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

# numPy
import numpy as np

# h5py
import h5py

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
    timestamp: datetime

# -------------------------------------------------------------------------------------
def _decode_uv8(f_data: np.ndarray, ff_dyn_range_min: float, ff_dyn_range_max: float,
                fi_nodata: int | None = None) -> np.ndarray:
    """
    decodifica um campo GAMIC UV8 para float32 (nodata é convertido para NaN).

    IMPORTANTE: a transformação linear abaixo deve ser validada contra a
                especificação/convenção GAMIC do radar.
    """
    # logger
    M_LOG.debug(">> _decode_uv8")

    l_raw = np.asarray(f_data)

    if l_raw.dtype != np.uint8:
        # raise an exception
        raise ValueError(f"UV8 esperado como uint8, recebido {l_raw.dtype}")

    l_result = (ff_dyn_range_min + l_raw.astype(np.float32) / 255.0 *
                (ff_dyn_range_max - ff_dyn_range_min))

    if fi_nodata is not None:
        l_result[l_raw == fi_nodata] = np.nan

    return l_result.astype(np.float32)

# -------------------------------------------------------------------------------------
def _attr_float(f_obj: h5py.Group | h5py.Dataset, fs_name: str,
                ff_default: float | None = None) -> float | None:
    """
    attr float
    """
    # logger
    M_LOG.debug(">> _attr_float")

    if fs_name not in f_obj.attrs:
        return ff_default

    l_value = f_obj.attrs[fs_name]

    if isinstance(l_value, np.ndarray):
        l_value = l_value.item()

    return float(l_value)

# -------------------------------------------------------------------------------------
def _attr_string(f_obj: h5py.Group | h5py.Dataset, fs_name: str,
                 fs_default: str | None = None) -> str | None:
    """
    attr float
    """
    # logger
    M_LOG.debug(">> _attr_string")

    if fs_name not in f_obj.attrs:
        return fs_default

    l_value = f_obj.attrs[fs_name]

    if isinstance(l_value, bytes):
        return l_value.decode("utf-8", errors="replace")

    return str(l_value)

# -------------------------------------------------------------------------------------
def _decode_moment(f_dataset: h5py.Dataset, *,
                   ff_dyn_range_min: float, ff_dyn_range_max: float) -> np.ndarray:
    """
    converte um dataset de momento GAMIC para float32

    No caso atual esperamos UV8.
    """
    # logger
    M_LOG.debug(">> _decode_moment")

    l_data = f_dataset[...]

    ls_data_format = f_dataset.attrs.get("format", "UV8")

    if isinstance(ls_data_format, bytes):
        ls_data_format = ls_data_format.decode("ascii", errors="replace")

    ls_data_format = str(ls_data_format).upper()

    if ls_data_format == "UV8":
        return _decode_uv8(l_data, ff_dyn_range_min, ff_dyn_range_max)

    if np.issubdtype(l_data.dtype, np.floating):
        return l_data.astype(np.float32)

    raise ValueError(
        f"Formato de momento não suportado: " f"{ls_data_format}, dtype={l_data.dtype}")

# -------------------------------------------------------------------------------------
def _decode_time(f_dataset: h5py.Dataset) -> datetime.datetime | None:
    """
    tenta recuperar o timestamp de um scan.

    a implementação aceita inicialmente os atributos date/time encontrados
    em diferentes variantes GAMIC.
    """
    # logger
    M_LOG.debug(">> _decode_time")

    # data e hora
    ls_date = _attr_string(f_dataset, "date")
    ls_time = _attr_string(f_dataset, "time")

    if not ls_date or not ls_time:
        # quit fail
        return None

    ls_value = f"{ls_date}T{ls_time}"

    ls_value = ls_value.replace("Z", "+00:00")

    try:
        ldt_result = datetime.datetime.fromisoformat(ls_value)

        if ldt_result.tzinfo is None:
            ldt_result = ldt_result.replace(tzinfo=datetime.timezone.utc)

        # ok
        return ldt_result

    except ValueError:
        # quit fail
        return None

# -------------------------------------------------------------------------------------
def _find_moment(f_scan_group: h5py.Group, fs_quantity: str) -> h5py.Dataset:
    """
    localiza o momento desejado dentro de um scan.

    atualmente o GAMIC observado utiliza moment_0 para Z.
    """
    # logger
    M_LOG.debug(">> _find_moment")

    for ls_name, l_obj in f_scan_group.items():

        if not isinstance(l_obj, h5py.Group):
            continue

        if not ls_name.startswith("moment_"):
            continue

        ls_moment = _attr_string(l_obj, "moment")

        if ls_moment is not None:
            ls_moment = ls_moment.upper()

        if ls_moment == fs_quantity.upper():
            # ok
            return l_obj

    # fallback para o caso conhecido
    l_candidate = f_scan_group.get("moment_0")

    if isinstance(l_candidate, h5py.Group):
        ls_moment = _attr_string(l_candidate, "moment")

        if ls_moment is None or ls_moment.upper() == fs_quantity.upper():
            # Normalmente o próprio grupo contém o dataset.
            for _, l_obj in l_candidate.items():
                if isinstance(l_obj, h5py.Dataset):
                    # ok
                    return l_obj

    # raise an exception
    raise KeyError(f"Momento {fs_quantity!r} não encontrado em " f"{f_scan_group.name}")

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
