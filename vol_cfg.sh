# Centro Logístico de Simulação Meteorológica
# Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo
#
# vol_cfg.sh
# variáveis de configuração compartilhadas
#
# 2026.nov  mlabru  cls_setup_pythonpath: pacote Python comum (cls_common)
#                   por CLS_PYLIB, no lugar dos symlinks apps/{dbase,radar,util}
#
# 2026.nov  mlabru  CLS_LIB obrigatória (passo 2): sai o symlink cls_common.sh
#                   da raiz do repo; sem cls.env/CLS_LIB, erro explícito
#
# 2026.nov  mlabru  - banco/CAPPIs compartilhados: sem sobreposição própria,
#                     vêm de CLS_DBASE_FILE/CLS_CAPPI_DIR (cls.env, sob
#                     CLS_ROOT) antes do padrão antigo
#
# 2026.nov  mlabru  - cls.env (CLS_ENV_FILE, padrão ~/.config/cls/cls.env)
#                     carregado antes dos padrões; cls_common.sh vem de
#                     CLS_LIB, com o symlink ao lado do script como reserva
#                   - prefixo met -> cls (cls_log, cls_check_test_env,
#                     CLS_ENV, CLS_TST_ROOT)
#
# 2026.out  mlabru  - comentários (refatoração para legibilidade; valores
#                     inalterados)
#                   - trava via cls_check_test_env (cls_common.sh): resolve os
#                     caminhos com realpath -m -- antes um caminho com ".."
#                     (<raiz>/../producao) passava pelo padrão "<raiz>"/*
#                   - ambiente de teste (cls.test, 03.dat/tst): VOL_SYNC_DIR,
#                     VOL_PATH e VOL_DBASE_FILE aceitam override pelo
#                     ambiente; servidor remoto (VOL_REMOTE_*) veio do
#                     vol_sync.sh para cá, também sobrescrevível
#                   - trava CLS_ENV=test: recusa servidor que não seja
#                     localhost e caminho fora de CLS_TST_ROOT -- o sync usa
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

# depends on: bash, cls_common.sh
# shellcheck shell=bash

# < configuração compartilhada >-------------------------------------------------------

# ambiente da instalação (cls.env: CLS_LIB e sobreposições), carregado
# antes dos padrões abaixo; "set -a" exporta para os programas Python.
# Precedência: ambiente do processo > cls.env > padrões deste arquivo (ver
# cls.common/etc/cls.env.example)
CLS_ENV_FILE="${CLS_ENV_FILE:-${HOME:-}/.config/cls/cls.env}"
if [ -r "${CLS_ENV_FILE}" ]; then set -a; source "${CLS_ENV_FILE}"; set +a; fi

# cada VOL_X="${VOL_X:-padrão}" abaixo usa o valor do ambiente, se houver
# (ambiente de teste, cls.test), senão o padrão de produção

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
# ordem: VOL_DBASE_FILE > CLS_DBASE_FILE (cls.env, raiz CLS_ROOT) > padrão
VOL_DBASE_FILE="${VOL_DBASE_FILE:-${CLS_DBASE_FILE:-${VOL_DATA}/dbase/catalog.db}}"

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

# cls_check_test_env (cls_common.sh, de CLS_LIB, do cls.env;
# comum aos projetos cls)
# CLS_LIB (cls.env) é obrigatória: sem ela não há cls_common.sh -- falha
# aqui, com a causa, em vez de num "command not found" mais adiante
if [ ! -r "${CLS_LIB:-}/cls_common.sh" ]; then
    echo "[error]: CLS_LIB='${CLS_LIB:-}' sem cls_common.sh; defina-a no cls.env (${CLS_ENV_FILE:-~/.config/cls/cls.env})" >&2
    exit 1
fi
source "${CLS_LIB}/cls_common.sh"

# com CLS_ENV=test (env.sh do cls.test), nada pode apontar para fora de
# CLS_TST_ROOT nem para um servidor que não seja esta máquina
cls_check_test_env -r "${VOL_REMOTE_IP}" "${VOL_SYNC_DIR}" "${VOL_PATH}" \
                      "${VOL_DBASE_FILE}" "${VOL_REMOTE_DIR}" || exit 1

# < pacote Python comum >--------------------------------------------------------------

# cls_common (dbase, radar, util; CLS_PYLIB no cls.env) no PYTHONPATH,
# exportado para todo programa Python chamado daqui (cls_common.sh)
cls_setup_pythonpath || exit 1

# < the end >--------------------------------------------------------------------------
