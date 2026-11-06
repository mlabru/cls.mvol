#!/usr/bin/env bash
#
# Centro Logístico de Simulação Meteorológica
# Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo
#
# tst_cycle.sh
# roda N ciclos do pipeline no ambiente de teste, na ordem do cron:
#
#   tst_feed.py -> vol_sync.sh -> vol_register.sh -> nwc_convert.sh
#   -> nwc_interpol.sh -> ofl_run.sh -> rsm_run.sh
#
# e mostra as contagens do banco ao fim de cada ciclo (tst_report.sh
# --counts).  Os scripts são os de produção, redirecionados pelo env.sh.
#
# uso: tst_cycle.sh [-r raiz] [--cycles N] (--hours H | --count N)
#                   [--drop-every K] [--drop P] [--no-mrad] [--no-oflow]
#
# 2026.out  mlabru  estágio ofl_run (25.oflow) depois do nwc_interpol
#                   (--no-oflow desliga)
#
# 2026.out  mlabru  initial version (Linux/Bash)

set -euo pipefail

# < configuração >---------------------------------------------------------------------

TST_ENV_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# < argumentos >-----------------------------------------------------------------------

LS_ROOT="$( cd "${TST_ENV_DIR}/../../.." && pwd )/03.dat/tst"
LI_CYCLES=1
LARR_FEED=()
LB_MRAD=true
LB_OFLOW=true

while [ $# -gt 0 ]; do
    case "$1" in
        -r) LS_ROOT="$2"; shift 2 ;;
        --cycles) LI_CYCLES="$2"; shift 2 ;;
        --hours|--count|--drop-every|--drop|--seed) LARR_FEED+=("$1" "$2"); shift 2 ;;
        --no-mrad) LB_MRAD=false; shift ;;
        --no-oflow) LB_OFLOW=false; shift ;;
        *) echo "uso: $0 [-r raiz] [--cycles N] (--hours H | --count N) [--drop-every K] [--drop P] [--no-mrad] [--no-oflow]" >&2
           exit 2 ;;
    esac
done

[ -f "${LS_ROOT}/env.sh" ] || { echo "[error]: ${LS_ROOT}/env.sh não existe; rode tst_setup.sh" >&2; exit 1; }

# shellcheck source=/dev/null
source "${LS_ROOT}/env.sh"

# Py-ART/h5py/cv2 para todos os estágios (os scripts herdam o PATH)
[ -f ~/.venv/bin/activate ] && source ~/.venv/bin/activate

# < funções >--------------------------------------------------------------------------

# roda um estágio e mostra o rc (não interrompe o ciclo, salvo o feed)
stage() {

    local ls_name="$1"; shift
    local li_rc=0

    "$@" > /dev/null 2>&1 || li_rc=$?

    printf '  %-16s rc=%d\n' "${ls_name}" "${li_rc}"
    return 0

} # stage

# < main >-----------------------------------------------------------------------------

for (( li = 1; li <= LI_CYCLES; li++ )); do
    echo "== ciclo ${li}/${LI_CYCLES} ($(date -u '+%F %T')Z)"

    python3 "${TST_ENV_DIR}/tst_feed.py" "${LARR_FEED[@]}"

    stage vol_sync       bash "${TST_MVOL_DIR}/vol_sync.sh"
    stage vol_register   bash "${TST_MVOL_DIR}/vol_register.sh"
    stage nwc_convert    bash "${TST_NWC_DIR}/nwc_convert.sh"
    stage nwc_interpol   bash "${TST_NWC_DIR}/nwc_interpol.sh"

    if ${LB_OFLOW}; then
        # env.sh antigo (antes do 25.oflow): rode tst_setup.sh de novo
        [ -n "${TST_OFL_DIR:-}" ] || { echo "[error]: env.sh sem TST_OFL_DIR; rode tst_setup.sh" >&2; exit 1; }
        stage ofl_run    bash "${TST_OFL_DIR}/ofl_run.sh"
    fi

    if ${LB_MRAD}; then
        stage rsm_run    bash "${TST_MRAD_DIR}/rsm_run.sh"
    fi

    bash "${TST_ENV_DIR}/tst_report.sh" -r "${LS_ROOT}" --counts
done

echo "logs: ${VOL_PATH}/logs, ${NWC_PATH}/logs, ${RSM_PATH}/logs, ${OFL_PATH:-?}/logs"

# < the end >--------------------------------------------------------------------------
