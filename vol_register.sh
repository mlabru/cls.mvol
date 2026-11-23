#!/usr/bin/env bash
#
# Centro Logístico de Simulação Meteorológica
# Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo
#
# vol_register.sh
# script cron-driven que registra os .mvol sincronizados por vol_sync.sh e
# aplica a retenção.
#
# workflow:
# - apps/volScan.py: varre VOL_SYNC_DIR e registra/atualiza cada .mvol na
#   tabela volumes do catalog.db compartilhado (incremental, timestamps
#   UTC);
# - apps/volPurge.py (se VOL_RETAIN_DAYS ou VOL_RETAIN_MIN_FREE_GB não for
#   vazio): retenção -- apaga os .mvol antigos que já têm produto final, e
#   a guarda de disco apaga os mais antigos quando o espaço livre cai abaixo
#   do mínimo (ver vol_cfg.sh).  Um volume sendo convertido está PROCESSING,
#   portanto pendente na view cappi_pending, e não é apagado (salvo
#   VOL_RETAIN_MAX_DAYS; a guarda de disco nunca apaga um PROCESSING).
#
# lock de instância próprio (.vol_register_instance.lock), independente do
# de vol_sync.sh e do nwc_convert.sh: um sync ou uma conversão lentos não
# bloqueiam o registro do que já chegou (o rsync só renomeia para *.mvol
# arquivos completos).
#
# 2026.nov  mlabru  limites da guarda de disco: VOL_RETAIN_DISK_MIN_AGE_H e
#                   VOL_RETAIN_DISK_MAX_GB repassados ao volPurge.py
#
# 2026.nov  mlabru  guarda de disco: volPurge.py também roda só com
#                   VOL_RETAIN_MIN_FREE_GB (--min-free-gb), sem VOL_RETAIN_DAYS
#
# 2026.nov  mlabru  - falha do volPurge.py sai com o rc dele (antes só [warn] e
#                     rc 0); o registro feito antes continua valendo
#                   - heartbeat VOL_REGISTER_OK_FILE no fim de toda execução
#                     bem sucedida, para o vol_check.sh
#
# 2026.out  mlabru  - normalização com 27.nowcast/25.oflow: acquire_instance_lock
#                     (mesmo nome do vol_sync.sh), VOL_REGISTER_NO_MAIN e nível
#                     [error] (era [erro]; o cls_common.sh e os outros
#                     projetos usam [error])
#                   - refatoração para legibilidade: run_scan, run_purge e main
#
# 2026.set  mlabru  - vol_convert.sh -> vol_register.sh
#                     ficam o registro e a retenção
#                   - retenção (volPurge.py); --remove-mvol e --failed-dir
#                     saíram do volProcess.py
#
# 2026.ago  mlabru  initial version (Linux/Bash)

# depends on: python3, apps/volScan.py, apps/volPurge.py

set -euo pipefail

# < configuração >---------------------------------------------------------------------

# diretório deste script (para localizar vol_cfg.sh)
LIB_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# variáveis de configuração
source "${LIB_DIR}/vol_cfg.sh"

# funções compartilhadas (check_log_size, log)
source "${LIB_DIR}/vol_common.sh"

# log do próprio shell (log()) e erros
VOL_LOG_APP="${VOL_LOGS}/vol_register.log"
VOL_LOG_ERR="${VOL_LOGS}/vol_register.err"

# stdout/stderr dos processos Python
VOL_LOG_SCAN_APP="${VOL_LOGS}/volScan.log"
VOL_LOG_SCAN_ERR="${VOL_LOGS}/volScan.err"
VOL_LOG_PURGE_APP="${VOL_LOGS}/volPurge.log"
VOL_LOG_PURGE_ERR="${VOL_LOGS}/volPurge.err"

# lock de instância -- evita dois registros simultâneos (cron disparando de
# novo antes do anterior terminar)
VOL_REGISTER_INSTANCE_LOCK="${VOL_STATE}/.vol_register_instance.lock"

# -------------------------------------------------------------------------------------
# registra os .mvol de VOL_SYNC_DIR na tabela volumes (volScan.py)
#
# retorno: o código de saída do volScan.py (0 = sucesso)
#
run_scan() {

    # rc capturado via '||' (com 'if !' o rc original se perderia)
    local li_rc=0

    python3 "${LIB_DIR}/apps/volScan.py" "${VOL_DBASE_FILE}" --raw-dir "${VOL_SYNC_DIR}" \
            >> "${VOL_LOG_SCAN_APP}" 2>> "${VOL_LOG_SCAN_ERR}" || li_rc=$?

    return "${li_rc}"

} # run_scan

# -------------------------------------------------------------------------------------
# aplica a retenção dos .mvol (volPurge.py).  só é chamada com
# VOL_RETAIN_DAYS e/ou VOL_RETAIN_MIN_FREE_GB preenchidos; VOL_RETAIN_MAX_DAYS
# é opcional (só com VOL_RETAIN_DAYS)
#
# retorno: o código de saída do volPurge.py (0 = sucesso)
#
run_purge() {

    local larr_purge_args=(--sync-dir "${VOL_SYNC_DIR}")
    local li_rc=0

    # retenção por idade (VOL_RETAIN_MAX_DAYS só com ela)
    if [ -n "${VOL_RETAIN_DAYS}" ]; then
        larr_purge_args+=(--retain-days "${VOL_RETAIN_DAYS}")

        if [ -n "${VOL_RETAIN_MAX_DAYS}" ]; then
            larr_purge_args+=(--max-days "${VOL_RETAIN_MAX_DAYS}")
        fi
    fi

    # guarda de disco
    if [ -n "${VOL_RETAIN_MIN_FREE_GB}" ]; then
        larr_purge_args+=(--min-free-gb "${VOL_RETAIN_MIN_FREE_GB}")

        # limites da guarda (vazios = padrões do volPurge.py)
        if [ -n "${VOL_RETAIN_DISK_MIN_AGE_H}" ]; then
            larr_purge_args+=(--disk-min-age-hours "${VOL_RETAIN_DISK_MIN_AGE_H}")
        fi

        if [ -n "${VOL_RETAIN_DISK_MAX_GB}" ]; then
            larr_purge_args+=(--disk-max-gb "${VOL_RETAIN_DISK_MAX_GB}")
        fi
    fi

    python3 "${LIB_DIR}/apps/volPurge.py" "${VOL_DBASE_FILE}" "${larr_purge_args[@]}" \
            >> "${VOL_LOG_PURGE_APP}" 2>> "${VOL_LOG_PURGE_ERR}" || li_rc=$?

    return "${li_rc}"

} # run_purge

# -------------------------------------------------------------------------------------
# adquire o lock de instância (fd 202, mantido aberto até o fim do script):
# impede dois registros simultâneos.  se outra instância já estiver
# rodando, sai com 0
#
acquire_instance_lock() {

    exec 202>"${VOL_REGISTER_INSTANCE_LOCK}"

    if ! flock -n 202; then
        # logger
        log "[info]: registro já em execução; saindo."
        # ok
        exit 0
    fi

} # acquire_instance_lock

# -------------------------------------------------------------------------------------
# fluxo principal:
#   1. diretórios, lock de instância e rotação dos logs dos filhos;
#   2. registro (volScan.py) -- falha aqui encerra com o mesmo rc, sem
#      retenção;
#   3. retenção (volPurge.py), se ligada -- falha sai com o rc dele;
#   4. heartbeat de sucesso (VOL_REGISTER_OK_FILE).
#
main() {

    local li_rc=0

    # diretórios -- precisa ser a primeira ação: log() escreve em VOL_LOGS e
    # o lock fica em VOL_STATE
    mkdir -p "${VOL_LOGS}" "${VOL_STATE}" "$(dirname "${VOL_DBASE_FILE}")"

    # logger
    log "-----------------------------------------------------------------"
    log "[info]: iniciando registro (retenção: ${VOL_RETAIN_DAYS:-desligada} d, mínimo livre: ${VOL_RETAIN_MIN_FREE_GB:-desligado} GB)..."

    acquire_instance_lock

    # rotação dos logs dos processos filhos
    check_log_size "${VOL_LOG_SCAN_APP}" "${VOL_LOG_SCAN_ERR}" \
                   "${VOL_LOG_PURGE_APP}" "${VOL_LOG_PURGE_ERR}"

    # módulos precisam estar em PYTHONPATH pois apps/ não é um package
    export PYTHONPATH="${LIB_DIR}/apps${PYTHONPATH:+:${PYTHONPATH}}"

    # 2. registro
    run_scan || li_rc=$?

    if [ "${li_rc}" -ne 0 ]; then
        # logger
        log "[error]: volScan.py falhou (rc=${li_rc}); retenção não executada. veja ${VOL_LOG_SCAN_ERR}"
        # quit fail
        exit "${li_rc}"
    fi

    # 3. retenção por idade e/ou guarda de disco (desligadas com
    #    VOL_RETAIN_DAYS e VOL_RETAIN_MIN_FREE_GB vazias)
    if [ -n "${VOL_RETAIN_DAYS}" ] || [ -n "${VOL_RETAIN_MIN_FREE_GB}" ]; then
        run_purge || li_rc=$?

        if [ "${li_rc}" -ne 0 ]; then
            # o registro já foi feito; o rc != 0 é para o cron/monitor ver
            # que a retenção falhou (antes só [warn] e rc 0)
            log "[error]: volPurge.py terminou com rc=${li_rc}; veja ${VOL_LOG_PURGE_ERR}"
            # quit fail
            exit "${li_rc}"
        fi
    fi

    # 4. último sucesso, para o vol_check.sh
    cls_heartbeat "${VOL_REGISTER_OK_FILE}"

    # logger
    log "[info]: registro concluído."

} # main

# < main >-----------------------------------------------------------------------------

# permite carregar as funções acima sem executar o main (testes)
[ "${VOL_REGISTER_NO_MAIN:-false}" = true ] && return 0

main

# < the end >--------------------------------------------------------------------------
