# Centro Logístico de Simulação Meteorológica
# Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo
#
# vol_cfg.sh
# variáveis de configuração compartilhadas
#
# 2026.out  mlabru  - comentários (refatoração para legibilidade; valores
#                     inalterados)
#                   - trava via met_check_test_env (met_common.sh): resolve os
#                     caminhos com realpath -m -- antes um caminho com ".."
#                     (<raiz>/../producao) passava pelo padrão "<raiz>"/*
#                   - ambiente de teste (tst_env/, 03.dat/tst): VOL_SYNC_DIR,
#                     VOL_PATH e VOL_DBASE_FILE aceitam override pelo
#                     ambiente; servidor remoto (VOL_REMOTE_*) veio do
#                     vol_sync.sh para cá, também sobrescrevível
#                   - trava MET_ENV=test: recusa servidor que não seja
#                     localhost e caminho fora de MET_TST_ROOT -- o sync usa
#                     --remove-source-files, e um teste apontado para o
#                     servidor real apagaria os .mvol do radar
#
# 2026.set  mlabru  - VOL_CAPPI, VOL_OUTPUT e VOL_PROCESS_WORKERS removidos;
#                     vol_convert.sh virou vol_register.sh
#                   - retenção: VOL_RETAIN_DAYS/VOL_RETAIN_MAX_DAYS
#                     (volPurge.py, passo 3 do vol_convert.sh);
#                     VOL_REMOVE_MVOL e VOL_FAILED removidos (o conversor
#                     não apaga nem move mais o .mvol)
#                   - blend removido: VOL_ASSETS e VOL_RAW (só usados por
#                     vol_blender.sh) removidos
#                   - VOL_DELETE_REMOTE e VOL_SYNC_MIN_AGE_MIN removidos:
#                     vol_sync.sh sempre remove a origem baixada e não usa
#                     mais o relógio do servidor
#                   - VOL_SYNC_DIR (destino do rsync, antes LOCAL_DIR fixo
#                     em vol_sync.sh), VOL_SYNC_MIN_AGE_MIN, VOL_CAPPI,
#                     VOL_FAILED, VOL_REMOVE_MVOL e VOL_PROCESS_WORKERS
#                     (vol_convert.sh)
#
# 2026.ago  mlabru  - VOL_DELETE_REMOTE adicionado -- toggle para
#                     vol_downloader.sh remover o .mvol do servidor remoto
#                     após download bem-sucedido
#                   - extraído de vol_downloader.sh/vol_blend.sh para
#                     eliminar duplicação
#                   - vol_blender.sh passa a usar o prefixo VOL_ para as
#                     variáveis compartilhadas
#
# 2026.jul  mlabru  initial version (Linux/Bash)

# depends on: bash, met_common.sh
# shellcheck shell=bash

# < configuração compartilhada >-------------------------------------------------------

# cada VOL_X="${VOL_X:-padrão}" abaixo usa o valor do ambiente, se houver
# (ambiente de teste, tst_env/), senão o padrão de produção

# destino local do rsync (vol_sync.sh), diretório varrido por volScan.py e
# podado por volPurge.py (vol_register.sh)
VOL_SYNC_DIR="${VOL_SYNC_DIR:-/mnt/usr.L02/${USER}/radar}"

# raiz de trabalho dos scripts (logs, locks, temporários, catalog.db)
VOL_PATH="${VOL_PATH:-/home/${USER}/Public/mvol}"

# logs
VOL_LOGS="${VOL_PATH}/logs"
# mvol folders
VOL_DATA="${VOL_PATH}/data"

# arquivos de estado (locks de instância)
VOL_STATE="${VOL_DATA}/state"
# arquivos temporários
VOL_TEMP="${VOL_DATA}/temp"

# catalog.db compartilhado, onde vol_sync.sh (volDBWriter.py) grava as
# observações de todo arquivo listado (fullpath, tempo do nome e mtime),
# para que se reconstrua a recepção mesmo depois que o .mvol de origem for
# removido
VOL_DBASE_FILE="${VOL_DBASE_FILE:-${VOL_DATA}/dbase/catalog.db}"

# servidor dos .mvol (vol_sync.sh): listado por ssh e baixado por rsync com
# --remove-source-files -- a origem é APAGADA depois da cópia
VOL_REMOTE_USER="${VOL_REMOTE_USER:-webpca}"
VOL_REMOTE_IP="${VOL_REMOTE_IP:-172.18.30.153}"
VOL_REMOTE_DIR="${VOL_REMOTE_DIR:-/home/webpca/radar}"

# limite de tamanho dos logs (10MB), usado na rotação simples de cada script
GI_LOG_MAX_SIZE=$((10 * 1024 * 1024))

# retenção dos .mvol em VOL_SYNC_DIR (volPurge.py): apaga o .mvol de um
# volume com mais de VOL_RETAIN_DAYS dias (pelo horário do volume) que já
# tem produto final; um .mvol ainda pendente só sai depois de
# VOL_RETAIN_MAX_DAYS (limite de disco; vazio = nunca).  VOL_RETAIN_DAYS
# vazio desliga a retenção -- manter vazio durante o desenvolvimento.  Sem o
# .mvol um volume não pode mais ser reconvertido (ex.: com um preset novo)
VOL_RETAIN_DAYS="${VOL_RETAIN_DAYS:-}"
VOL_RETAIN_MAX_DAYS="${VOL_RETAIN_MAX_DAYS:-}"

# < trava do ambiente de teste >-------------------------------------------------------

# met_check_test_env (met_common.sh, symlink para 04.dvl/bash, comum aos
# projetos met)
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/met_common.sh"

# com MET_ENV=test (tst_env/env.sh), nada pode apontar para fora de
# MET_TST_ROOT nem para um servidor que não seja esta máquina
met_check_test_env -r "${VOL_REMOTE_IP}" "${VOL_SYNC_DIR}" "${VOL_PATH}" \
                      "${VOL_DBASE_FILE}" "${VOL_REMOTE_DIR}" || exit 1

# < the end >--------------------------------------------------------------------------
