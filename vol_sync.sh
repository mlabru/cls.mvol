#!/usr/bin/env bash
#
# Centro Logístico de Simulação Meteorológica
# Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo
#
# vol_sync.sh
# script cron-driven que sincroniza (rsync) os arquivos .mvol do servidor
# remoto para VOL_SYNC_DIR, de onde são registrados por vol_register.sh
# (volScan.py).
#
# workflow:
# - via ssh (uma única chamada), lista (find -name '*.mvol') todos os
#   .mvol completos em REMOTE_DIR -- em gravação, o arquivo tem nome
#   *.mvol.????? e só é renomeado para *.mvol ao terminar;
# - persiste a listagem completa no catalog.db compartilhado via volDBWriter
#   (tempo do nome + mtime), antes de mover qualquer arquivo -- é o único
#   histórico de recepção desses arquivos.  Se a gravação falhar, nada é
#   baixado nem removido;
# - rsync --files-from com os arquivos DESTA listagem para VOL_SYNC_DIR,
#   sempre removendo a origem (--remove-source-files): este script é o único
#   responsável pelos downloads do servidor.
#
#
# 2026.out  mlabru  - nível [error] (era [erro]), como o cls_common.sh e os
#                     outros projetos
#                   - refatoração para legibilidade: corpo do main dividido
#                     em ensure_directories, acquire_instance_lock,
#                     persist_listing e main
#                   - fix: horário das linhas de erro em VOL_LOG_ERR em UTC
#                     (date -u), como o log()
#                   - REMOTE_* vêm de VOL_REMOTE_* (vol_cfg.sh), sobrescrevíveis
#                     pelo ambiente de teste (ssh localhost + inbox local);
#                     a trava MET_ENV=test do vol_cfg.sh impede o servidor real
#
# 2026.set  mlabru  - listagem com caminho relativo a REMOTE_DIR (find
#                     -printf '%P'): o catalog.db não guarda mais o prefixo
#                     do servidor, e build_transfer_list não precisa mais
#                     cortá-lo (sem argumento)
#                   - simplificado: sem "date +%s" do servidor nem filtro de
#                     idade mínima (o relógio do servidor não é confiável; o
#                     tempo do volume vem do nome, gravado por volDBWriter). 
#                     o filtro é desnecessário: arquivo incompleto no
#                     servidor tem nome *.mvol.?????  até o rename final, e
#                     o find só lista *.mvol
#                   - --remove-source-files sempre (VOL_DELETE_REMOTE e
#                     VOL_SYNC_MIN_AGE_MIN removidos de vol_cfg.sh)
#                   - falha ao gravar no catalog.db aborta a sincronização
#                     (antes só [warn]): com remoção sempre ligada, seria
#                     perda definitiva do registro de recepção
#                   - lista de transferência (--files-from) restrita aos
#                     arquivos da listagem já gravada no catalog.db e com
#                     idade mínima VOL_SYNC_MIN_AGE_MIN: fecha a janela em
#                     que um arquivo chegava entre o find e o rsync e era
#                     movido sem registro, e evita copiar/apagar um .mvol
#                     ainda em gravação pelo radar
#                   - --remove-source-files só com VOL_DELETE_REMOTE=true
#                     (antes era incondicional, ignorando o toggle)
#                   - ssh/rsync com BatchMode/ConnectTimeout/ServerAlive e
#                     --timeout: cron não trava mais segurando o lock
#                   - LOCAL_DIR fixo substituído por VOL_SYNC_DIR (vol_cfg.sh)
#
# 2026.ago  mlabru  - garante a criação do diretório do catalog.db (mkdir
#                     -p) antes da primeira gravação via volDBWriter.py
#                   - lock de instância compartilhado, log()/check_log_size
#                     de vol_common.sh, persistência no catalog.db via
#                     volDBWriter
#
# 2026.set  mlabru  initial version (Linux/Bash)

# depends on: python, rsync, ssh e acesso ssh (por chave) ao servidor remoto

set -euo pipefail

# < configuração >---------------------------------------------------------------------

# nome do computador
HOST=$(hostname)

# diretório deste script (para localizar vol_cfg.sh)
LIB_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# variáveis de configuração
source "${LIB_DIR}/vol_cfg.sh"

# host remoto (vol_cfg.sh, sobrescrevível pelo ambiente)
VOL_REMOTE_HOST="${VOL_REMOTE_USER}@${VOL_REMOTE_IP}"

# funções compartilhadas
source "${LIB_DIR}/vol_common.sh"

# log files
VOL_LOG_APP="${VOL_LOGS}/vol_sync.log"
VOL_LOG_ERR="${VOL_LOGS}/vol_sync.err"

# lock de instância: é o que impede a execução simultânea de dois processos
VOL_INSTANCE_LOCK="${VOL_STATE}/.vol_sync_instance.lock"

# opções de ssh (também usadas pelo rsync): BatchMode impede que o cron fique
# parado num prompt de senha; ConnectTimeout/ServerAlive* derrubam conexões
# penduradas em vez de segurar o lock de instância indefinidamente
MT_SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=20 -o ServerAliveInterval=15 -o ServerAliveCountMax=3)

# timeout de I/O do rsync (segundos sem transferência)
GI_RSYNC_TIMEOUT=120

# -------------------------------------------------------------------------------------
# converte uma listagem "mtime|caminho" (stdin; caminho já relativo a
# VOL_REMOTE_DIR, find -printf '%P') na lista de rsync --files-from, ignorando
# linhas sem '|'
#
# uso: build_transfer_list
#
build_transfer_list() {

    # o caminho é tudo após o primeiro '|'
    awk 'index($0, "|") > 0 { print substr($0, index($0, "|") + 1) }'

} # build_transfer_list

# -------------------------------------------------------------------------------------
# lista os .mvol do servidor remoto numa única chamada ssh, uma linha
# "mtime|caminho" por arquivo, caminho relativo a VOL_REMOTE_DIR (%P: é o que
# vai para o catalog.db e para o --files-from) -- o mtime é só informativo (hora de chegada
# pelo relógio do servidor); nenhuma decisão aqui depende dele
#
list_remote_files() {

    # logger
    log "[info]: listando os arquivos do servidor..."

    # parameters
    local ls_output

    # conecta via ssh e gera lista de arquivos do servidor
    # stderr real do ssh vai para VOL_LOG_ERR em caso de falha
    if ! ls_output=$(ssh "${MT_SSH_OPTS[@]}" "${VOL_REMOTE_HOST}" \
        "find '${VOL_REMOTE_DIR}/' -type f -name '*.mvol' -printf '%T@|%P\n'" 2>&1); then
        # logger
        echo "[$(date -u '+%F %T')] [error]: ssh falhou ao listar '${VOL_REMOTE_HOST}': ${ls_output}" >> "${VOL_LOG_ERR}"
        # quit fail
        return 1
    fi

    # ok
    echo "${ls_output}"

} # list_remote_files

# -------------------------------------------------------------------------------------
# baixa os .mvol da lista de transferência para VOL_SYNC_DIR via rsync,
# removendo do servidor cada arquivo copiado com sucesso -- a persistência
# no catalog.db (main, abaixo) já garante que alguém reconstrua a recepção
# depois dessa remoção
#
# uso: sync_files <arquivo_lista_de_transferência>
#
sync_files() {

    # parameters
    local ls_files_from="$1"
    local ls_rsync_out

    # logger
    log "[info]: sincronizando ${VOL_REMOTE_HOST}:${VOL_REMOTE_DIR} -> ${VOL_SYNC_DIR} ..."

    # -a: arquivamento (permissões, timestamps, links)
    # -v: verboso (saída registrada em VOL_LOG_APP abaixo, para auditoria)
    # -z: compressão em trânsito
    # --files-from: só os caminhos (relativos a VOL_REMOTE_DIR) já gravados no
    #     catalog.db nesta execução (um arquivo que chegue depois do find
    #     fica para a próxima rodada); implica --relative, recriando os
    #     subdiretórios estação/alcance no destino
    # --remove-source-files: apaga a origem só depois da cópia completa.  um
    #     .mvol em gravação nunca chega aqui: o gravador usa o nome
    #     temporário *.mvol.?????  e só renomeia (atômico) para *.mvol ao
    #     terminar, e o find de list_remote_files só lista -name '*.mvol'. 
    #     a partir do rsync 3.1 (no servidor), a origem também não é apagada
    #     se o tamanho/mtime mudar durante a cópia -- só uma rede de
    #     segurança extra
    # o rsync grava cada arquivo num temporário oculto e renomeia ao final --
    # volScan.py nunca vê um .mvol parcial
    local larr_opts=(-avz --timeout="${GI_RSYNC_TIMEOUT}" -e "ssh ${MT_SSH_OPTS[*]}"
                     --files-from="${ls_files_from}" --remove-source-files)

    if ! ls_rsync_out=$(rsync "${larr_opts[@]}" \
            "${VOL_REMOTE_HOST}:${VOL_REMOTE_DIR}/" "${VOL_SYNC_DIR}/" 2>&1); then
        # stderr real do rsync vai para VOL_LOG_ERR
        echo "[$(date -u '+%F %T')] [error]: rsync falhou: ${ls_rsync_out}" >> "${VOL_LOG_ERR}"
        # quit fail
        return 1
    fi

    # saída verbosa do rsync, para auditoria do que foi sincronizado
    echo "${ls_rsync_out}" >> "${VOL_LOG_APP}"

    # ok
    return 0

} # sync_files

# -------------------------------------------------------------------------------------
# cria os diretórios de trabalho.  precisa ser a primeira ação do main: log()
# escreve em VOL_LOGS e o lock fica em VOL_STATE.  VOL_SYNC_DIR é o destino
# do rsync; o diretório do catalog.db é criado aqui para que
# sqlite3.connect() (volDBWriter.py) consiga criar o arquivo na primeira
# gravação, mesmo numa máquina recém-provisionada
#
ensure_directories() {

    mkdir -p "${VOL_SYNC_DIR}" "${VOL_DATA}" "${VOL_LOGS}" "${VOL_STATE}" \
             "${VOL_TEMP}" "$(dirname "${VOL_DBASE_FILE}")"

} # ensure_directories

# -------------------------------------------------------------------------------------
# adquire o lock de instância (fd 200, mantido aberto até o fim do script):
# impede duas sincronizações simultâneas lendo/movendo do mesmo
# VOL_REMOTE_DIR.  se outra instância já estiver rodando, sai com 0
#
acquire_instance_lock() {

    exec 200>"${VOL_INSTANCE_LOCK}"

    if ! flock -n 200; then
        # logger
        log "[info]: sincronização já em execução; saindo."
        # ok
        exit 0
    fi

} # acquire_instance_lock

# -------------------------------------------------------------------------------------
# grava no catalog.db TODAS as observações da listagem (volDBWriter.py),
# antes do rsync remover os arquivos de origem -- sem esse registro, a
# recepção desses arquivos se perderia para sempre
#
# uso: persist_listing <listagem "mtime|caminho">
# retorno: 0 se gravou, 1 se falhou
#
persist_listing() {

    # parameters
    local ls_listing="$1"

    echo "${ls_listing}" \
        | python3 "${LIB_DIR}/apps/volDBWriter.py" "${VOL_DBASE_FILE}" 2>>"${VOL_LOG_ERR}"

} # persist_listing

# -------------------------------------------------------------------------------------
# fluxo principal:
#   1. diretórios e lock de instância;
#   2. lista os .mvol do servidor (uma chamada ssh);
#   3. grava a listagem no catalog.db -- se falhar, ABORTA sem baixar nada;
#   4. monta a lista de transferência com os arquivos desta listagem;
#   5. rsync com remoção da origem.
#
main() {

    # parameters
    local ls_remote_output

    ensure_directories

    # logger
    log "-----------------------------------------------------------------"
    log "[info]: iniciando sincronização (host=${HOST})..."

    acquire_instance_lock

    # 2. lista os arquivos do servidor remoto
    if ! ls_remote_output=$(list_remote_files); then
        # logger
        log "[warn]: falha ao listar '${VOL_REMOTE_HOST}'; abortando sincronização."
        # quit fail
        exit 1
    fi

    if [ -z "${ls_remote_output}" ]; then
        # logger
        log "[info]: nenhum .mvol no servidor; nada a sincronizar."
        # ok
        exit 0
    fi

    # 3. registro antes de qualquer remoção: falha aqui aborta
    if ! persist_listing "${ls_remote_output}"; then
        # logger
        log "[error]: falha ao persistir observações no catalog.db; abortando sem baixar/remover nada."
        # quit fail
        exit 1
    fi

    # 4. lista de transferência (temporária, removida ao sair).  variável
    #    global: o trap roda depois que main já retornou
    VOL_FILES_FROM=$(mktemp -p "${VOL_TEMP}" vol_sync.XXXXXX)
    trap 'rm -f "${VOL_FILES_FROM}"' EXIT

    build_transfer_list <<< "${ls_remote_output}" > "${VOL_FILES_FROM}"

    # logger
    log "[info]: arquivos a transferir: $(grep -c . "${VOL_FILES_FROM}" || true)"

    # 5. sincroniza (falha só avisa: o que não veio fica para a próxima rodada)
    if ! sync_files "${VOL_FILES_FROM}"; then
        # logger
        log "[warn]: falha ao sincronizar arquivos."
    fi

    # logger
    log "[info]: sincronização concluída."

} # main

# < main >-----------------------------------------------------------------------------

# permite carregar as funções acima sem executar o main (testes)
[ "${VOL_SYNC_NO_MAIN:-false}" = true ] && return 0

main

# < the end >--------------------------------------------------------------------------
