# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

vol_catalog
estrutura de persistência das observações de recepção radar

fullpath é o caminho RELATIVO ao diretório remoto (REMOTE_DIR), no formato
<estação>/<RRR>/<EEE>-<RRR>--<AAAA-MM-DD>--<HH-MM-SS>.mvol, como sai de
find -printf '%P'.  O prefixo do servidor não serve a nenhum consumidor; os
diretórios sim, e a unicidade (UNIQUE) só funciona se todo arquivo for gravado
sempre no mesmo formato (ver check_relpath()).

escritor único: vol_sync.sh (volDBWriter.py, source='mvol').  O monrad
(21.mrad) só lê a tabela, pelo mesmo arquivo via symlink.  Linhas antigas com
source='monrad' são de quando ele também gravava.

2026.out  mlabru  - docstrings: o 21.mvol é o único escritor (o monrad passou a
                    abrir o catalog.db somente leitura)

2026.set  mlabru  - fullpath passa a ser relativo a REMOTE_DIR (antes, o
                    caminho absoluto no servidor); check_relpath(), guarda
                    comum dos escritores
                  - coluna obs_time renomeada para timestamp (INTEGER),
                    mesmo nome/conteúdo de volumes.timestamp;
                    ensure_schema() migra (RENAME COLUMN) e troca o índice
                  - coluna obs_time (epoch UTC extraído do nome do .mvol, o
                    único tempo confiável -- mtime vem do relógio do
                    servidor e fica só como hora de chegada bruta) e
                    ensure_schema(), que migra bases antigas (ALTER TABLE
                    ADD COLUMN)

2026.ago  mlabru  initial version (Linux/Python)
"""
# < constants >────────────────────────────────────────────────────────────────────────

# nome da tabela (prefixo "vol_" para não colidir com as tabelas de outros
# programas no mesmo catalog.db)
CS_TABLE = "vol_raw_observations"

# contrato: qualquer mudança de schema precisa ser replicada também
# fullpath: relativo a REMOTE_DIR (ver docstring do módulo)
CS_CREATE_TABLE = f"""
CREATE TABLE IF NOT EXISTS {CS_TABLE} (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    fullpath   TEXT    NOT NULL UNIQUE,
    mtime      REAL    NOT NULL,
    timestamp  INTEGER,
    source     TEXT    NOT NULL,
    created_at TEXT
)
"""

CS_CREATE_INDEX = f"""
CREATE INDEX IF NOT EXISTS vol_raw_observations_idx_mtime ON {CS_TABLE}(mtime)
"""

# separado de CS_CREATE_INDEX: numa base antiga (sem timestamp) o índice só
# pode ser criado depois da migração de ensure_schema() -- quem ainda só
# executa CS_CREATE_TABLE/CS_CREATE_INDEX continua funcionando
CS_CREATE_INDEX_TIMESTAMP = f"""
CREATE INDEX IF NOT EXISTS vol_raw_observations_idx_timestamp ON {CS_TABLE}(timestamp)
"""

# índice da coluna com o nome antigo (obs_time), removido na migração
CS_DROP_INDEX_OBS_TIME = "DROP INDEX IF EXISTS vol_raw_observations_idx_obs_time"

# ─────────────────────────────────────────────────────────────────────────────────────
def check_relpath(fs_path: str) -> None:
    """
    confere que fs_path está no formato de fullpath (relativo a REMOTE_DIR)

    gravar o caminho absoluto (listagem antiga, find sem '%P') duplicaria
    cada arquivo já registrado com o caminho relativo, já que a deduplicação
    é pelo texto de fullpath

    :param fs_path: caminho a gravar

    :raises ValueError: caminho vazio ou absoluto
    """
    if not fs_path:
        raise ValueError("fullpath vazio")

    if fs_path.startswith('/'):
        raise ValueError(f"fullpath absoluto (esperado relativo a REMOTE_DIR): {fs_path}")

# ─────────────────────────────────────────────────────────────────────────────────────
def ensure_schema(fconn) -> None:
    """
    garante tabela e índices, migrando bases antigas: coluna obs_time (nome
    anterior) é renomeada para timestamp; base sem nenhuma das duas ganha
    timestamp (nullable: linhas de quem não sabe extrair o tempo do nome
    ficam NULL)

    numa base migrada por RENAME a coluna mantém a afinidade REAL declarada
    antes -- os valores continuam comparáveis a volumes.timestamp (a
    comparação no SQLite é numérica)

    :param fconn: conexão sqlite3 aberta
    """
    # tabela e índice originais
    fconn.execute(CS_CREATE_TABLE)
    fconn.execute(CS_CREATE_INDEX)

    # colunas existentes
    lset_cols = {lt_row[1] for lt_row in fconn.execute(f"PRAGMA table_info({CS_TABLE})")}

    # base antiga ? migra
    if "timestamp" not in lset_cols:
        if "obs_time" in lset_cols:
            # nome anterior da mesma coluna
            fconn.execute(f"ALTER TABLE {CS_TABLE} RENAME COLUMN obs_time TO timestamp")

        else:
            # base anterior à coluna
            fconn.execute(f"ALTER TABLE {CS_TABLE} ADD COLUMN timestamp INTEGER")

    # o índice antigo acompanha o RENAME, mas com o nome obsoleto
    fconn.execute(CS_DROP_INDEX_OBS_TIME)

    # índice do tempo confiável
    fconn.execute(CS_CREATE_INDEX_TIMESTAMP)

# < the end >──────────────────────────────────────────────────────────────────────────
