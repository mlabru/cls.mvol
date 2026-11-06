# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

test_volAudit
testes unitários de volAudit (cruzamento observações × volumes, somente
leitura)

2026.set  mlabru  fullpath das observações relativo a REMOTE_DIR
2026.set  mlabru  volumes interpolados/previstos fora do cruzamento
2026.set  mlabru  initial version (Linux/Python)
"""
# < imports >──────────────────────────────────────────────────────────────────────────

# python library
import datetime
import hashlib
import sqlite3

# model
import dbase.vol_catalog as ct
import dbase.vol_dbase as vd
import volAudit as va

# < constants >────────────────────────────────────────────────────────────────────────

# instantes de referência (UTC)
MI_T0 = int(datetime.datetime(2026, 4, 12, 0, 0, tzinfo=datetime.timezone.utc).timestamp())
MI_T1 = MI_T0 + 600
MI_T2 = MI_T0 + 1200

# "agora" bem depois de todos os volumes (fora da carência)
MF_NOW = MI_T0 + 86400.

# ─────────────────────────────────────────────────────────────────────────────────────
def _name(fs_station: str, fi_range: int, fi_ts: int, fs_suffix: str = "") -> str:
    """
    nome .mvol do volume (EEE-RRR--YYYY-MM-DD--HH-MM-SS.mvol)
    """
    ldt = datetime.datetime.fromtimestamp(fi_ts, datetime.timezone.utc)
    return f"{fs_station}-{fi_range}--{ldt:%Y-%m-%d--%H-%M-%S}{fs_suffix}.mvol"


def _setup(ftmp, flst_obs: list, flst_vol: list) -> str:
    """
    cria o catalog.db com as duas tabelas

    :param flst_obs: nomes (basename) listados no servidor
    :param flst_vol: (radar, alcance, timestamp) registrados em volumes
    """
    ls_db = str(ftmp / "catalog.db")

    lconn = sqlite3.connect(ls_db)
    ct.ensure_schema(lconn)

    for ls_sql in vd.MT_CREATE_ALL:
        lconn.execute(ls_sql)

    for li_idx, ls_name in enumerate(flst_obs):
        lconn.execute(f"INSERT INTO {ct.CS_TABLE} (fullpath, mtime, source) VALUES (?, ?, ?)",
                      (f"Estacao/000/{ls_name}", float(MI_T0 + li_idx), "mvol"))

    for ls_radar, li_alcance, li_ts in flst_vol:
        lconn.execute("INSERT INTO volumes (radar, alcance, timestamp, fullpath) "
                      "VALUES (?, ?, ?, ?)",
                      (ls_radar, li_alcance, li_ts,
                       f"/mnt/radar/{_name(ls_radar, li_alcance, li_ts)}"))

    lconn.commit()
    lconn.close()

    return ls_db

# ─────────────────────────────────────────────────────────────────────────────────────
def test_tudo_casado_sem_divergencias(tmp_path):
    ls_db = _setup(tmp_path, [_name("CGU", 250, MI_T0), _name("CGU", 250, MI_T1)],
                   [("CGU", 250, MI_T0), ("CGU", 250, MI_T1)])

    ldct = va.audit(ls_db, ff_now=MF_NOW)

    assert [] == ldct["unregistered"] == ldct["unlisted"] == ldct["invalid"]
    assert (MI_T0, MI_T1) == ldct["window"]


def test_tres_categorias(tmp_path):
    ls_db = _setup(tmp_path,
                   [_name("CGU", 250, MI_T0), _name("CGU", 250, MI_T2), "lixo.mvol"],
                   [("CGU", 250, MI_T0), ("CGU", 250, MI_T1)])

    ldct = va.audit(ls_db, ff_now=MF_NOW)

    # T2 listado e não registrado; T1 registrado e não listado (dentro da janela)
    assert [("CGU", 250, MI_T2)] == [lt_key for lt_key, _ in ldct["unregistered"]]
    assert [("CGU", 250, MI_T1)] == [lt_key for lt_key, _ in ldct["unlisted"]]
    assert ["Estacao/000/lixo.mvol"] == [ls for ls, _ in ldct["invalid"]]


def test_registro_fora_da_janela_nao_e_orfao(tmp_path):
    """
    volumes mais velhos que a observação mais antiga (histórico de
    observações mais curto que o de volumes, ex.: base podada no passado)
    não são acusados
    """
    ls_db = _setup(tmp_path, [_name("CGU", 250, MI_T1)],
                   [("CGU", 250, MI_T0), ("CGU", 250, MI_T1)])

    assert [] == va.audit(ls_db, ff_now=MF_NOW)["unlisted"]


def test_carencia(tmp_path):
    """
    volume listado há menos de --grace minutos ainda não é acusado
    """
    ls_db = _setup(tmp_path, [_name("CGU", 250, MI_T0)], [])

    assert [] == va.audit(ls_db, fi_grace_min=30, ff_now=MI_T0 + 10 * 60)["unregistered"]
    assert 1 == len(va.audit(ls_db, fi_grace_min=30, ff_now=MI_T0 + 31 * 60)["unregistered"])


def test_copia_1_cai_no_mesmo_volume(tmp_path):
    ls_db = _setup(tmp_path, [_name("CGU", 250, MI_T0), _name("CGU", 250, MI_T0, "(1)")],
                   [("CGU", 250, MI_T0)])

    ldct = va.audit(ls_db, ff_now=MF_NOW)

    assert [] == ldct["unregistered"] == ldct["unlisted"] == ldct["invalid"]


def test_filtro_de_estacao(tmp_path):
    ls_db = _setup(tmp_path, [_name("CGU", 250, MI_T0), _name("GAF", 400, MI_T0)],
                   [("CGU", 250, MI_T0)])

    assert [] == va.audit(ls_db, fs_station="cgu", ff_now=MF_NOW)["unregistered"]
    assert 1 == len(va.audit(ls_db, fs_station="GAF", ff_now=MF_NOW)["unregistered"])


def test_nao_escreve_no_banco(tmp_path):
    ls_db = _setup(tmp_path, [_name("CGU", 250, MI_T0)], [("CGU", 250, MI_T1)])
    ls_before = hashlib.sha1(open(ls_db, "rb").read()).hexdigest()

    va.print_report(va.audit(ls_db, ff_now=MF_NOW))

    assert ls_before == hashlib.sha1(open(ls_db, "rb").read()).hexdigest()

# -------------------------------------------------------------------------------------
def test_volumes_sinteticos_do_nowcast_sao_ignorados(tmp_path):
    """
    interpolado (status 4, fullpath .npy) e previsto (status 5) dentro da
    janela não são "registro sem servidor" -- só contados
    """
    ls_db = _setup(tmp_path, [_name("CGU", 250, MI_T0), _name("CGU", 250, MI_T2)],
                   [("CGU", 250, MI_T0), ("CGU", 250, MI_T2)])

    lconn = sqlite3.connect(ls_db)
    lconn.execute("INSERT INTO volumes (radar, alcance, timestamp, fullpath, status, interpolated) "
                  "VALUES ('CGU', 250, ?, ?, 4, 1)", (MI_T1, f"/cappi/CGU_250_{MI_T1}.npy"))
    lconn.execute("INSERT INTO volumes (radar, alcance, timestamp, fullpath, status, predicted) "
                  "VALUES ('CGU', 250, ?, ?, 5, 1)", (MI_T1 + 300, f"/cappi/CGU_250_{MI_T1 + 300}.npy"))
    lconn.commit()
    lconn.close()

    ldct = va.audit(ls_db, ff_now=MF_NOW)

    assert [] == ldct["unlisted"]
    assert 2 == ldct["synthetic"]

# < the end >──────────────────────────────────────────────────────────────────────────
