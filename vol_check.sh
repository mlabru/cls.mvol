#!/usr/bin/env bash
#
# Centro Logístico de Simulação Meteorológica
# Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo
#
# vol_check.sh
# verificação EXTERNA do 21.mvol para monitoramento: confere a idade dos
# heartbeats de sucesso que vol_sync.sh e vol_register.sh gravam ao fim de
# cada execução bem sucedida (cls_heartbeat).  Existe porque os crons só
# registram as falhas nos próprios .err: se um deles parar (cron removido,
# host caído, lock preso) ou passar a falhar sempre, ninguém fica sabendo
# até alguém ler os logs.  Não depende dos crons estarem rodando.
#
# para cada heartbeat (VOL_SYNC_OK_FILE, VOL_REGISTER_OK_FILE):
# - ausente ou ilegível (o script nunca terminou bem)  -> UNKNOWN  (3)
# - mais velho que VOL_CHECK_MAX_AGE_MIN minutos        -> CRITICAL (2)
# - senão                                               -> OK       (0)
# o resultado é o pior dos dois; saída de uma linha no formato dos plugins
# do Nagios (como o g19_check.sh do 23.goes).
#
# uso: vol_check.sh
#   ex.: */10 * * * * bash <VOL_ROOT>/vol_check.sh > /dev/null || <notificar>
#
# 2026.nov  mlabru  initial version (Linux/Bash)

# depends on: bash, coreutils, vol_cfg.sh (cls_common.sh: cls_check_heartbeat)

set -euo pipefail

# < configuração >---------------------------------------------------------------------

# diretório deste script (para localizar vol_cfg.sh)
LIB_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# variáveis de configuração (e cls_common.sh)
source "${LIB_DIR}/vol_cfg.sh"

# códigos de saída (plugins do Nagios)
readonly GI_EXIT_OK=0
readonly GI_EXIT_CRITICAL=2
readonly GI_EXIT_UNKNOWN=3

# -------------------------------------------------------------------------------------
# rótulo do pior código: CRITICAL vence UNKNOWN (um script parado é pior do
# que um que nunca rodou neste host)
#
# uso: worst_label <rc>
#
worst_label() {

    case "$1" in
        "${GI_EXIT_OK}")       echo "OK" ;;
        "${GI_EXIT_CRITICAL}") echo "CRITICAL" ;;
        *)                     echo "UNKNOWN" ;;
    esac

} # worst_label

# -------------------------------------------------------------------------------------
# fluxo principal:
#   1. confere cada heartbeat (cls_check_heartbeat);
#   2. junta as frases numa linha e sai com o pior código.
#
main() {

    local li_rc li_worst="${GI_EXIT_OK}"
    local ls_msg
    local larr_msgs=()
    local ls_label ls_file

    for ls_label in vol_sync vol_register; do
        case "${ls_label}" in
            vol_sync)     ls_file="${VOL_SYNC_OK_FILE}" ;;
            vol_register) ls_file="${VOL_REGISTER_OK_FILE}" ;;
        esac

        li_rc=0
        ls_msg="$(cls_check_heartbeat "${ls_label}" "${ls_file}" "${VOL_CHECK_MAX_AGE_MIN}")" || li_rc=$?
        larr_msgs+=("${ls_msg}")

        # pior: CRITICAL (2) > UNKNOWN (3) > OK (0)
        if [ "${li_rc}" -eq "${GI_EXIT_CRITICAL}" ]; then
            li_worst="${GI_EXIT_CRITICAL}"
        elif [ "${li_rc}" -ne "${GI_EXIT_OK}" ] && [ "${li_worst}" -eq "${GI_EXIT_OK}" ]; then
            li_worst="${GI_EXIT_UNKNOWN}"
        fi
    done

    # uma linha: "<ESTADO>: frase; frase"
    ls_msg="$(printf '%s; ' "${larr_msgs[@]}")"
    echo "$(worst_label "${li_worst}"): ${ls_msg%; }"

    exit "${li_worst}"

} # main

# < main >-----------------------------------------------------------------------------

# permite carregar as funções acima sem executar o main (testes)
[ "${VOL_CHECK_NO_MAIN:-false}" = true ] && return 0

main

# < the end >--------------------------------------------------------------------------
