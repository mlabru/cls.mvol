# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

test_volScan
testes unitários de volScan (registro dos .mvol na tabela volumes:
timestamp UTC, varredura incremental, nomes inválidos)

2026.out  mlabru  o SHA1 roda sem lock de escrita; reconferência na escrita
2026.set  mlabru  initial version (Linux/Python)
"""
# < imports >──────────────────────────────────────────────────────────────────────────

# python library
import datetime
import sqlite3

# model
import dbase.vol_dbase as vd
import volScan as vs

# < helpers >──────────────────────────────────────────────────────────────────────────

def _tree(ftmp):
    """
    árvore estação/alcance/arquivo como a sincronizada por vol_sync.sh
    """
    lpth_dir = ftmp / "raw" / "Cangucu" / "250"
    lpth_dir.mkdir(parents=True)

    (lpth_dir / "CGU-250--2026-06-15--13-40-22.mvol").write_bytes(b"abc")
    (lpth_dir / "CGU-250--2026-06-15--13-50-22.mvol").write_bytes(b"")
    (lpth_dir / "lixo.mvol").write_bytes(b"")
    # temporário do rsync: não termina em .mvol
    (lpth_dir / ".CGU-250--2026-06-15--14-00-22.mvol.Ab12Cd").write_bytes(b"")

    return ftmp / "raw"

# ─────────────────────────────────────────────────────────────────────────────────────
def test_scan_registra_com_timestamp_utc(tmp_path):
    ls_db = str(tmp_path / "catalog.db")

    ldct = vs.scan(ls_db, [_tree(tmp_path)])

    assert {"inserted": 2, "updated": 0, "skipped": 0, "ignored": 1} == ldct

    # 13:40:22 do nome é UTC (o nc_scan_mvol gravava +3h)
    li_expected = int(datetime.datetime(2026, 6, 15, 13, 40, 22,
                                        tzinfo=datetime.timezone.utc).timestamp())

    with vd.transaction(ls_db) as ldb:
        lrow = ldb.get_volume("CGU", 250, li_expected)

    assert lrow is not None
    assert 3 == lrow["filesize"]
    # SHA1 de b"abc"
    assert "a9993e364706816aba3e25717850c26c9cd0d89d" == lrow["sha1"]

# -------------------------------------------------------------------------------------
def test_scan_incremental_pula_inalterados(tmp_path):
    ls_db = str(tmp_path / "catalog.db")
    lpth_raw = _tree(tmp_path)

    vs.scan(ls_db, [lpth_raw])

    # segunda varredura: nada muda, SHA1 não é recalculado
    ldct = vs.scan(ls_db, [lpth_raw])
    assert (0, 0, 2) == (ldct["inserted"], ldct["updated"], ldct["skipped"])

    # arquivo alterado: update
    (lpth_raw / "Cangucu" / "250" / "CGU-250--2026-06-15--13-40-22.mvol").write_bytes(b"abcd")

    ldct = vs.scan(ls_db, [lpth_raw])
    assert (0, 1, 1) == (ldct["inserted"], ldct["updated"], ldct["skipped"])

# -------------------------------------------------------------------------------------
def test_scan_mantem_registro_de_copia_duplicada(tmp_path):
    ls_db = str(tmp_path / "catalog.db")
    lpth_raw = _tree(tmp_path)

    vs.scan(ls_db, [lpth_raw])

    # cópia "(1)" do mesmo volume: mesmo radar/alcance/timestamp
    (lpth_raw / "Cangucu" / "250" / "CGU-250--2026-06-15--13-40-22(1).mvol").write_bytes(b"zz")

    ldct = vs.scan(ls_db, [lpth_raw])

    assert 0 == ldct["updated"]
    assert 2 == ldct["ignored"]   # lixo.mvol + a cópia

# -------------------------------------------------------------------------------------
def test_scan_diretorio_inexistente(tmp_path):
    ldct = vs.scan(str(tmp_path / "catalog.db"), [tmp_path / "nao_existe"])

    assert {"inserted": 0, "updated": 0, "skipped": 0, "ignored": 0} == ldct

# -------------------------------------------------------------------------------------
def test_scan_sha1_sem_lock_de_escrita(tmp_path, monkeypatch):
    """
    durante o SHA1 outro processo (o nwcConvert) consegue o lock de escrita
    sem esperar: a varredura não segura BEGIN IMMEDIATE durante o I/O
    """
    ls_db = str(tmp_path / "catalog.db")
    lpth_raw = _tree(tmp_path)
    llst_ok = []

    lv_sha1 = vs.calculate_sha1

    def sha1_com_escritor(fpth_file):
        lconn = sqlite3.connect(ls_db, timeout=0)

        try:
            lconn.execute("BEGIN IMMEDIATE")
            lconn.rollback()
            llst_ok.append(fpth_file.name)

        finally:
            lconn.close()

        return lv_sha1(fpth_file)

    monkeypatch.setattr(vs, "calculate_sha1", sha1_com_escritor)

    ldct = vs.scan(ls_db, [lpth_raw])

    assert 2 == ldct["inserted"]
    assert 2 == len(llst_ok)

# -------------------------------------------------------------------------------------
def test_scan_reconfere_na_escrita(tmp_path, monkeypatch):
    """
    volume registrado por outro processo entre a leitura e a escrita: vira
    skip (mesmo arquivo) em vez de IntegrityError no INSERT
    """
    ls_db = str(tmp_path / "catalog.db")
    lpth_raw = _tree(tmp_path)
    lpth_file = lpth_raw / "Cangucu" / "250" / "CGU-250--2026-06-15--13-40-22.mvol"

    lv_sha1 = vs.calculate_sha1

    def sha1_com_concorrente(fpth_file):
        ls_sha1 = lv_sha1(fpth_file)

        if fpth_file == lpth_file:
            li_ts = int(datetime.datetime(2026, 6, 15, 13, 40, 22,
                                          tzinfo=datetime.timezone.utc).timestamp())
            with vd.transaction_write(ls_db) as ldb:
                ldb.insert_volume("CGU", 250, li_ts, str(lpth_file.resolve()), 3, ls_sha1)

        return ls_sha1

    monkeypatch.setattr(vs, "calculate_sha1", sha1_com_concorrente)

    ldct = vs.scan(ls_db, [lpth_raw])

    assert {"inserted": 1, "updated": 0, "skipped": 1, "ignored": 1} == ldct

# -------------------------------------------------------------------------------------
def test_scan_copias_novas_na_mesma_varredura(tmp_path):
    """
    duas cópias de um volume novo: a primeira é gravada, a outra ignorada
    """
    ls_db = str(tmp_path / "catalog.db")
    lpth_raw = _tree(tmp_path)

    (lpth_raw / "Cangucu" / "250" / "CGU-250--2026-06-15--13-40-22(1).mvol").write_bytes(b"zz")

    ldct = vs.scan(ls_db, [lpth_raw])

    assert {"inserted": 2, "updated": 0, "skipped": 0, "ignored": 2} == ldct

# < the end >──────────────────────────────────────────────────────────────────────────
