# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

rd_gamic_reader
leitura de volumes GAMIC HDF5 (GamicReader)

2026.nov  mlabru  - decodificação HDF5 (_decode_uv8, _decode_moment,
                    _decode_time, _find_moment, _attr_*) veio de rd_mvol:
                    o parser de nome não depende mais de h5py/numpy
                  - fix: UV8 bruto 0 (sem dado) vira NaN, como no Py-ART;
                    antes virava dyn_range_min (-32 dBZ) e passava como eco
                  - fix: lê o layout GAMIC real (validado contra
                    03.dat/lmc15.ori e pyart.aux_io.read_gamic): metadados do
                    scan em scan<N>/how (elevation, range_start, range_step *
                    range_samples, timestamp) e moment_<N> como Dataset.  O
                    leitor só conhecia scan<N>/where e momentos em Group, e
                    falhava em todo .mvol real (KeyError 'where')
                  - scans lidos em ordem numérica (scan10 vinha antes de scan2)
                  - logger em INFO (era DEBUG: trace por chamada vazava)

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
M_LOG.setLevel(logging.INFO)

# < constants >────────────────────────────────────────────────────────────────────────

# valor bruto UV8 "sem dado" (convenção GAMIC, igual ao Py-ART)
MI_UV8_NODATA = 0

# < decodificação GAMIC (h5py) >─────────────────────────────────────────────────────

# -------------------------------------------------------------------------------------
def _decode_uv8(f_data: np.ndarray, ff_dyn_range_min: float, ff_dyn_range_max: float,
                fi_nodata: int | None = None) -> np.ndarray:
    """
    decodifica um campo GAMIC UV8 para float32 (nodata é convertido para NaN).

    escala min + raw/255 * (max - min), a mesma do Py-ART
    (pyart.aux_io.gamicfile), que também mascara raw == 0
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
    attr string
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

    No caso atual esperamos UV8.  O valor bruto 0 é "sem dado" (abaixo do
    limiar / fora de cobertura) e vira NaN, como no Py-ART -- sem isso cada
    gate vazio virava dyn_range_min (-32 dBZ) e passava como eco válido.
    """
    # logger
    M_LOG.debug(">> _decode_moment")

    l_data = f_dataset[...]

    ls_data_format = f_dataset.attrs.get("format", "UV8")

    if isinstance(ls_data_format, bytes):
        ls_data_format = ls_data_format.decode("ascii", errors="replace")

    ls_data_format = str(ls_data_format).upper()

    if ls_data_format == "UV8":
        return _decode_uv8(l_data, ff_dyn_range_min, ff_dyn_range_max, MI_UV8_NODATA)

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

    # layout GAMIC real: scan<N>/how.timestamp ("2026-07-22T14:40:24.209Z")
    ls_value = None

    if isinstance(f_dataset.get("how"), h5py.Group):
        ls_value = _attr_string(f_dataset["how"], "timestamp")

    if not ls_value:
        # variante com date/time no próprio scan
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

    atualmente o GAMIC observado utiliza moment_0 para Z.  No GAMIC real
    moment_<N> é um Dataset com os atributos moment/format/dyn_range_*; a
    variante com um Group que contém o dataset continua aceita.
    """
    # logger
    M_LOG.debug(">> _find_moment")

    for ls_name, l_obj in f_scan_group.items():

        if not ls_name.startswith("moment_"):
            continue

        ls_moment = _attr_string(l_obj, "moment")

        if ls_moment is not None:
            ls_moment = ls_moment.upper()

        if ls_moment == fs_quantity.upper():
            # ok
            return _moment_dataset(l_obj)

    # fallback para o caso conhecido
    l_candidate = f_scan_group.get("moment_0")

    if isinstance(l_candidate, h5py.Dataset):
        # ok (GAMIC real: moment_0 é o Z)
        return l_candidate

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
def _moment_dataset(f_obj: h5py.Group | h5py.Dataset) -> h5py.Dataset:
    """
    o dataset de um momento: ele próprio (GAMIC real) ou o primeiro dataset
    do grupo (variante antiga)
    """
    if isinstance(f_obj, h5py.Dataset):
        return f_obj

    for _, l_obj in f_obj.items():
        if isinstance(l_obj, h5py.Dataset):
            return l_obj

    # raise an exception
    raise KeyError(f"Momento sem dataset: {f_obj.name}")

# -------------------------------------------------------------------------------------
def _scan_attr_float(f_group: h5py.Group, ft_names: tuple) -> float | None:
    """
    primeiro atributo encontrado de ft_names ((grupo, atributo), na ordem),
    onde grupo é "where"/"how" do scan ou "" (o próprio scan)
    """
    for ls_group, ls_attr in ft_names:
        l_obj = f_group if not ls_group else f_group.get(ls_group)

        if not isinstance(l_obj, h5py.Group):
            continue

        lf_value = _attr_float(l_obj, ls_attr)

        if lf_value is not None:
            return lf_value

    # não encontrado
    return None


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

        # feixe (no GAMIC real, um dataset composto; campos por nome)
        l_ray_header = f_group["ray_header"]

        # elevação: where.elangle (ODIM), how.elevation (GAMIC real) ou o
        # atributo fixed_angle do scan
        lf_elevation = _scan_attr_float(f_group, (("where", "elangle"), ("how", "elevation"),
                                                  ("", "fixed_angle")))

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
        l_moment = _find_moment(f_group, self.quantity)

        # dynamic range
        lf_dyn_min = _attr_float(l_moment, "dyn_range_min", -32.0)
        lf_dyn_max = _attr_float(l_moment, "dyn_range_max", 95.5)

        # dados
        l_data = _decode_moment(l_moment, ff_dyn_range_min=lf_dyn_min, ff_dyn_range_max=lf_dyn_max)

        # alcance: where.rstart/rscale (ODIM) ou how.range_start/range_step
        # (GAMIC real).  No GAMIC o passo efetivo é range_step * range_samples,
        # como no Py-ART (pyart.aux_io.gamic_hdf5)
        lf_range_start = _scan_attr_float(f_group, (("where", "rstart"), ("how", "range_start")))

        if lf_range_start is None:
            lf_range_start = 0.0

        lf_range_step = _scan_attr_float(f_group, (("where", "rscale"), ("where", "range_step")))

        if lf_range_step is None:
            lf_range_step = _scan_attr_float(f_group, (("how", "range_step"),))

            if lf_range_step is not None:
                lf_range_step *= _scan_attr_float(f_group, (("how", "range_samples"),)) or 1.0

        if lf_range_step is None:
            # raise an exception
            raise ValueError(f"Resolução de range não encontrada em " f"{f_group.name}")

        # data e hora
        ldt_timestamp = _decode_time(f_group) or fdt_volume_timestamp

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
        lf_latitude = _attr_float(l_where, "lat")

        if lf_latitude is None:
            # raise an exception
            raise ValueError("latitude do radar não encontrada")

        # converted longitude
        lf_longitude = _attr_float(l_where, "lon")

        if lf_longitude is None:
            # raise an exception
            raise ValueError("longitude do radar não encontrada")

        # converted altitude
        lf_altitude = _attr_float(l_where, "height")

        if lf_altitude is None:
            # raise an exception
            raise ValueError("altitude do radar não encontrada")

        # scans list
        llst_scans: list[rs.RadarScan] = []

        # scan names
        llst_scan_names = sorted((ls_name for ls_name in f_h5
                                          if re.fullmatch(r"scan\d+", ls_name) and
                                             isinstance(f_h5[ls_name], h5py.Group)),
                                 key=lambda ls_name: int(ls_name[4:]))

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
