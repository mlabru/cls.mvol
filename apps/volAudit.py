# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

volAudit
auditoria (somente leitura) do catalog.db compartilhado: cruza o que a
listagem remota de vol_sync.sh viu (vol_catalog.CS_TABLE, gravada por
volDBWriter.py) com o que volScan.py registrou (tabela volumes).

chave do cruzamento: (radar, alcance, timestamp) -- em volumes é a própria
chave única; nas observações é extraída do nome do arquivo
(rd_mvol.parse_mvol), de modo que uma cópia "(1)" cai no mesmo volume.  os
fullpath não são comparáveis (relativo a REMOTE_DIR × local em
VOL_SYNC_DIR).

categorias:
  1) servidor sem registro -- listado no servidor e ausente de volumes, com
     timestamp mais velho que --grace (dá tempo ao vol_register.sh): perda no
     rsync ou volScan.py que não rodou;
  2) registro sem servidor -- volume real (.mvol, não interpolado nem
     previsto) em volumes e ausente das observações, dentro da janela
     coberta por elas: cópia manual para VOL_SYNC_DIR, volDBWriter.py que
     falhou;
  3) nome inválido -- observação cujo nome não segue o padrão .mvol.

a janela da categoria 2 é a faixa [menor, maior] timestamp das observações.
abre o banco somente para leitura (mode=ro): nunca cria, migra nem escreve.

uso:
    python volAudit.py [catalog.db] [-s EEE] [--grace MIN] [-c]

2026.out  mlabru  refatoração para legibilidade: audit() e print_report()
                  divididos numa função por etapa/seção; status por
                  vol_dbase.CI_STATUS_* em vez de números mágicos

2026.set  mlabru  - fullpath das observações agora é relativo a REMOTE_DIR
                    (rótulos)
                  - fix: volumes interpolados/previstos não entram no
                    cruzamento -- eram acusados como "registro sem servidor"

2026.set  mlabru  initial version (Linux/Python)
"""
# < imports >──────────────────────────────────────────────────────────────────────────

# python library
from __future__ import annotations

import argparse
import datetime
import logging
import pathlib
import sqlite3
import sys
import time

# locals
import radar.rd_mvol as mv
import dbase.vol_catalog as ct
import dbase.vol_dbase as vd

# < constants >────────────────────────────────────────────────────────────────────────

# catalog.db padrão (data/dbase/catalog.db, relativo à raiz do projeto)
MPTH_DBASE = pathlib.Path(__file__).resolve().parent.parent / "data" / "dbase" / "catalog.db"

# carência (min) antes de acusar um volume listado e ainda não registrado:
# cobre o intervalo entre vol_sync.sh (registra a observação) e
# vol_register.sh (volScan.py registra o volume)
MI_GRACE_MIN = 30

# nomes dos status de volumes, só para exibição
MDCT_STATUS = {vd.CI_STATUS_NEW: "NEW",
               vd.CI_STATUS_PROCESSING: "PROCESSING",
               vd.CI_STATUS_DONE: "DONE",
               vd.CI_STATUS_FAILED: "FAILED",
               vd.CI_STATUS_INTERPOLATED: "INTERPOLATED",
               vd.CI_STATUS_PREDICTED: "PREDICTED"}

# status de volumes gerados, sem .mvol no servidor
MT_STATUS_SYNTHETIC = (vd.CI_STATUS_INTERPOLATED, vd.CI_STATUS_PREDICTED)

# < logging >──────────────────────────────────────────────────────────────────────────

# logger
M_LOG = logging.getLogger(__name__)
M_LOG.setLevel(logging.INFO)

# ─────────────────────────────────────────────────────────────────────────────────────
def arg_parse():
    """
    lê os argumentos da linha de comando

    :returns: argparse.Namespace com dbase, station, grace e count
    """
    # logger
    M_LOG.debug(">> arg_parse")

    # create parser
    lparser = argparse.ArgumentParser(
                 description=f"Audita o catalog.db: {ct.CS_TABLE} (vol_sync) × volumes (volScan).")

    # caminho do catalog.db compartilhado
    lparser.add_argument("dbase", nargs='?', default=str(MPTH_DBASE), type=str,
                         help=f"caminho do catalog.db (default: {MPTH_DBASE}).")

    # filtros
    lparser.add_argument("-s", "--station", dest="station", type=str, default=None,
                         help="só esta estação (sigla, ex.: CGU).")
    lparser.add_argument("--grace", dest="grace", type=int, default=MI_GRACE_MIN,
                         help=f"minutos de carência para volumes ainda não registrados "
                              f"(default: {MI_GRACE_MIN}).")
    lparser.add_argument("-c", "--count", dest="count", action="store_true",
                         help="mostra só as contagens.")

    # ok
    return lparser.parse_args()

# ─────────────────────────────────────────────────────────────────────────────────────
def fmt_epoch(ff_epoch) -> str:
    """
    converte epoch em data/hora UTC legível (mesmo formato de volDBList)

    :param ff_epoch: epoch em segundos, ou None

    :returns: "AAAA-MM-DD HH:MM:SS", ou "-" se ff_epoch for None
    """
    # sem valor
    if ff_epoch is None:
        return "-"

    ldt_utc = datetime.datetime.fromtimestamp(ff_epoch, datetime.timezone.utc)

    # ok
    return ldt_utc.strftime("%Y-%m-%d %H:%M:%S")

# < leitura e cruzamento >─────────────────────────────────────────────────────────────

def _read_tables(fs_dbase_path: str) -> tuple:
    """
    lê as duas tabelas do catalog.db, somente leitura (mode=ro: não cria o
    arquivo se ele não existir)

    :raises sqlite3.Error: banco inexistente, tabela ausente, ...

    :returns: (observações [(fullpath, mtime)],
               volumes [(radar, alcance, timestamp, fullpath, status,
                         interpolated, predicted)])
    """
    lconn = sqlite3.connect(f"file:{fs_dbase_path}?mode=ro", uri=True, timeout=10)

    try:
        llst_observations = lconn.execute(
            f"SELECT fullpath, mtime FROM {ct.CS_TABLE}").fetchall()

        llst_volumes = lconn.execute(
            "SELECT radar, alcance, timestamp, fullpath, status, "
            "interpolated, predicted FROM volumes").fetchall()

    finally:
        lconn.close()

    # ok
    return llst_observations, llst_volumes

# ─────────────────────────────────────────────────────────────────────────────────────
def _index_observations(flst_observations: list, fs_station: str | None) -> tuple:
    """
    indexa as observações pela chave do volume extraída do nome

    :param flst_observations: [(fullpath, mtime)]
    :param fs_station: sigla em maiúsculas (None = todas)

    :returns: ({(radar, alcance, timestamp): (fullpath, mtime)},
               [(fullpath, mtime)] das observações com nome inválido)
    """
    ldct_observations = {}
    llst_invalid = []

    for ls_fullpath, lf_mtime in flst_observations:
        try:
            l_mvol = mv.parse_mvol(ls_fullpath)

        # nome fora do padrão / alcance desconhecido
        except ValueError:
            llst_invalid.append((ls_fullpath, lf_mtime))
            # next
            continue

        lt_key = (l_mvol.product.station, l_mvol.product.range_km,
                  int(l_mvol.timestamp.timestamp()))

        # filtro de estação
        if fs_station and fs_station != lt_key[0]:
            # next
            continue

        # cópias "(1)" do mesmo volume: guarda a primeira
        ldct_observations.setdefault(lt_key, (ls_fullpath, lf_mtime))

    # ok
    return ldct_observations, llst_invalid

# ─────────────────────────────────────────────────────────────────────────────────────
def _is_synthetic_volume(fs_fullpath, fi_status, fi_interpolated, fi_predicted) -> bool:
    """
    True se o volume foi gerado (interpolado/previsto) e, portanto, nunca
    teve um .mvol no servidor
    """
    if fi_interpolated or fi_predicted:
        return True

    if fi_status in MT_STATUS_SYNTHETIC:
        return True

    # ok
    return not str(fs_fullpath).lower().endswith(".mvol")

# ─────────────────────────────────────────────────────────────────────────────────────
def _index_real_volumes(flst_volumes: list, fs_station: str | None) -> tuple:
    """
    indexa os volumes reais (com .mvol) pela chave única; os sintéticos só
    são contados

    :param flst_volumes: linhas lidas por _read_tables
    :param fs_station: sigla em maiúsculas (None = todas)

    :returns: ({(radar, alcance, timestamp): (fullpath, status)},
               nº de volumes sintéticos ignorados)
    """
    ldct_volumes = {}
    li_synthetic = 0

    for ls_radar, li_alcance, li_ts, ls_fullpath, li_status, li_interp, li_pred in flst_volumes:
        # filtro de estação
        if fs_station and fs_station != ls_radar:
            # next
            continue

        if _is_synthetic_volume(ls_fullpath, li_status, li_interp, li_pred):
            li_synthetic += 1
            # next
            continue

        ldct_volumes[(ls_radar, li_alcance, li_ts)] = (ls_fullpath, li_status)

    # ok
    return ldct_volumes, li_synthetic

# ─────────────────────────────────────────────────────────────────────────────────────
def _find_unregistered(fdct_observations: dict, fdct_volumes: dict,
                       ff_grace_limit: float) -> list:
    """
    categoria 1: listado no servidor, ausente de volumes, e com horário
    anterior ao fim da carência

    :returns: lista ordenada de (chave, (fullpath, mtime))
    """
    llst_unregistered = []

    for lt_key, lt_observation in fdct_observations.items():
        if lt_key in fdct_volumes:
            continue

        # ainda dentro da carência: vol_register.sh pode não ter rodado
        if lt_key[2] > ff_grace_limit:
            continue

        llst_unregistered.append((lt_key, lt_observation))

    # ok
    return sorted(llst_unregistered)

# ─────────────────────────────────────────────────────────────────────────────────────
def _observation_window(fdct_observations: dict) -> tuple | None:
    """
    faixa de horários coberta pelas observações

    :returns: (menor timestamp, maior timestamp), ou None se não houver
              observações
    """
    if not fdct_observations:
        return None

    llst_timestamps = [lt_key[2] for lt_key in fdct_observations]

    # ok
    return min(llst_timestamps), max(llst_timestamps)

# ─────────────────────────────────────────────────────────────────────────────────────
def _find_unlisted(fdct_observations: dict, fdct_volumes: dict,
                   ft_window: tuple | None) -> list:
    """
    categoria 2: volume real em volumes, ausente das observações, dentro da
    janela coberta por elas (fora da janela não há como saber)

    :returns: lista ordenada de (chave, (fullpath, status))
    """
    if ft_window is None:
        return []

    li_window_start, li_window_end = ft_window

    llst_unlisted = []

    for lt_key, lt_volume in fdct_volumes.items():
        if lt_key in fdct_observations:
            continue

        if not li_window_start <= lt_key[2] <= li_window_end:
            continue

        llst_unlisted.append((lt_key, lt_volume))

    # ok
    return sorted(llst_unlisted)

# ─────────────────────────────────────────────────────────────────────────────────────
def audit(fs_dbase_path: str, fs_station: str | None = None,
          fi_grace_min: int = MI_GRACE_MIN, ff_now: float | None = None) -> dict:
    """
    cruza observações × volumes (categorias na docstring do módulo).  fluxo:

    1. lê as duas tabelas (_read_tables);
    2. indexa cada uma pela chave (radar, alcance, timestamp);
    3. compara os índices nos dois sentidos.

    :param fs_dbase_path: caminho do catalog.db
    :param fs_station: sigla da estação (None = todas; maiúsculas ou não)
    :param fi_grace_min: carência (min) da categoria "servidor sem registro"
    :param ff_now: instante de referência (epoch; None = agora) -- para testes

    :raises sqlite3.Error: banco/tabela ilegível

    :returns: dict com as listas "unregistered", "unlisted", "invalid", o
              nº de volumes sintéticos ignorados "synthetic" e a janela
              "window" (min, max) ou None
    """
    # logger
    M_LOG.debug(">> audit")

    lf_now = ff_now

    if lf_now is None:
        lf_now = time.time()

    lf_grace_limit = lf_now - fi_grace_min * 60

    ls_station = None

    if fs_station:
        ls_station = fs_station.upper()

    llst_observations, llst_volumes = _read_tables(fs_dbase_path)

    ldct_observations, llst_invalid = _index_observations(llst_observations, ls_station)
    ldct_volumes, li_synthetic = _index_real_volumes(llst_volumes, ls_station)

    lt_window = _observation_window(ldct_observations)

    # ok
    return {"unregistered": _find_unregistered(ldct_observations, ldct_volumes, lf_grace_limit),
            "unlisted": _find_unlisted(ldct_observations, ldct_volumes, lt_window),
            "invalid": sorted(llst_invalid),
            "synthetic": li_synthetic,
            "window": lt_window}

# < relatório >────────────────────────────────────────────────────────────────────────

def _print_counts(fdct_result: dict) -> None:
    """
    imprime a janela e a contagem de cada categoria
    """
    lt_window = fdct_result["window"]

    if lt_window:
        print(f"janela: {fmt_epoch(lt_window[0])} .. {fmt_epoch(lt_window[1])} (UTC)")

    else:
        print("janela: vazia (nenhuma observação com nome válido)")

    print(f"servidor sem registro: {len(fdct_result['unregistered'])}")
    print(f"registro sem servidor: {len(fdct_result['unlisted'])}")
    print(f"nome inválido:         {len(fdct_result['invalid'])}")
    print(f"(volumes interpolados/previstos ignorados: {fdct_result['synthetic']})")

# ─────────────────────────────────────────────────────────────────────────────────────
def _print_unregistered(flst_unregistered: list) -> None:
    """
    imprime a categoria 1 (servidor sem registro), se houver
    """
    if not flst_unregistered:
        return

    print("\n# servidor sem registro (em observações, ausente de volumes)")
    print(f"{'radar':5}  {'alcance':>7}  {'timestamp (UTC)':19}  {'mtime (UTC)':19}  "
          f"fullpath (relativo a REMOTE_DIR)")

    for (ls_radar, li_alcance, li_ts), (ls_fullpath, lf_mtime) in flst_unregistered:
        print(f"{ls_radar:5}  {li_alcance:>7}  {fmt_epoch(li_ts):19}  {fmt_epoch(lf_mtime):19}  "
              f"{ls_fullpath}")

# ─────────────────────────────────────────────────────────────────────────────────────
def _print_unlisted(flst_unlisted: list) -> None:
    """
    imprime a categoria 2 (registro sem servidor), se houver
    """
    if not flst_unlisted:
        return

    print("\n# registro sem servidor (em volumes, ausente de observações)")
    print(f"{'radar':5}  {'alcance':>7}  {'timestamp (UTC)':19}  {'status':12}  fullpath (local)")

    for (ls_radar, li_alcance, li_ts), (ls_fullpath, li_status) in flst_unlisted:
        ls_status_name = MDCT_STATUS.get(li_status, str(li_status))

        print(f"{ls_radar:5}  {li_alcance:>7}  {fmt_epoch(li_ts):19}  "
              f"{ls_status_name:12}  {ls_fullpath}")

# ─────────────────────────────────────────────────────────────────────────────────────
def _print_invalid(flst_invalid: list) -> None:
    """
    imprime a categoria 3 (nome inválido), se houver
    """
    if not flst_invalid:
        return

    print("\n# nome inválido (observações fora do padrão .mvol)")
    print(f"{'mtime (UTC)':19}  fullpath (relativo a REMOTE_DIR)")

    for ls_fullpath, lf_mtime in flst_invalid:
        print(f"{fmt_epoch(lf_mtime):19}  {ls_fullpath}")

# ─────────────────────────────────────────────────────────────────────────────────────
def print_report(fdct_result: dict, fb_count: bool = False) -> None:
    """
    imprime o relatório na saída padrão

    :param fdct_result: retorno de audit()
    :param fb_count: True = só as contagens, sem as listas
    """
    # logger
    M_LOG.debug(">> print_report")

    _print_counts(fdct_result)

    if fb_count:
        return

    _print_unregistered(fdct_result["unregistered"])
    _print_unlisted(fdct_result["unlisted"])
    _print_invalid(fdct_result["invalid"])

# ─────────────────────────────────────────────────────────────────────────────────────
def main() -> int:
    """
    drive app

    :returns: 0 em caso de sucesso (com ou sem divergências), 1 se o banco
              não puder ser lido
    """
    # logger
    M_LOG.debug(">> main")

    # parse args
    largs = arg_parse()

    try:
        # cruza as tabelas e imprime
        print_report(audit(largs.dbase, largs.station, largs.grace), largs.count)

    # em caso de erro (banco inexistente, tabela ausente, ...)
    except sqlite3.Error as lerr:
        # logger
        M_LOG.error("falha ao ler %s: %s", largs.dbase, lerr)
        # quit fail
        return 1

    # saída fechada antes do fim (ex.: | head)
    except BrokenPipeError:
        # ok
        return 0

    # ok
    return 0

# ─────────────────────────────────────────────────────────────────────────────────────
# this is the bootstrap process

if "__main__" == __name__:
    # logger
    logging.basicConfig(datefmt="%Y/%m/%d %H:%M",
                        format="%(asctime)s %(message)s",
                        level=logging.INFO)

    # rd_mvol/vol_product_key forçam DEBUG no próprio logger: sem isto, cada
    # observação gera traces ">> parse_mvol" no stderr
    logging.getLogger("radar.rd_mvol").setLevel(logging.WARNING)
    logging.getLogger("dbase.vol_product_key").setLevel(logging.WARNING)

    # run
    sys.exit(main())

# < the end >──────────────────────────────────────────────────────────────────────────
