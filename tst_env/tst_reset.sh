#!/usr/bin/env bash
#
# Centro Logístico de Simulação Meteorológica
# Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo
#
# tst_reset.sh
# zera os dados do ambiente de teste (inbox, radar/, banco, CAPPIs, logs,
# cursor do alimentador); mantém env.sh e nowcast/config.ini.  A origem
# (TST_SRC, lmc15.ori) nunca é tocada: o inbox só tem hardlinks e radar/
# só tem cópias do rsync.
#
# uso: tst_reset.sh [-r raiz] --yes
#
# 2026.out  mlabru  initial version (Linux/Bash)

set -euo pipefail

TST_ENV_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

LS_ROOT="$( cd "${TST_ENV_DIR}/../../.." && pwd )/03.dat/tst"
LB_YES=false

while [ $# -gt 0 ]; do
    case "$1" in
        -r) LS_ROOT="$2"; shift 2 ;;
        --yes) LB_YES=true; shift ;;
        *) echo "uso: $0 [-r raiz] --yes" >&2; exit 2 ;;
    esac
done

# shellcheck source=/dev/null
source "${LS_ROOT}/env.sh"

die() { echo "[error]: $*" >&2; exit 1; }

# a raiz precisa ser a do env.sh, um ambiente de teste, e não conter a origem
LS_REAL="$(realpath -e "${LS_ROOT}")"

[ "${MET_ENV:-}" = test ] || die "env.sh sem MET_ENV=test"
[ "${LS_REAL}" = "$(realpath -m "${MET_TST_ROOT}")" ] || die "raiz ${LS_REAL} != MET_TST_ROOT ${MET_TST_ROOT}"
[ "${LS_REAL}" != / ] && [ "${LS_REAL}" != "${HOME}" ] || die "raiz perigosa: ${LS_REAL}"

case "$(realpath -m "${TST_SRC}")/" in
    "${LS_REAL}/"*) die "a origem ${TST_SRC} está dentro da raiz" ;;
esac

LARR_TARGETS=("${LS_REAL}/inbox" "${LS_REAL}/radar" "${LS_REAL}/feed" "${LS_REAL}/mvol"
              "${LS_REAL}/mrad" "${LS_REAL}/nowcast/data" "${LS_REAL}/nowcast/logs"
              "${LS_REAL}/oflow/logs" "${LS_REAL}/oflow/data/output"
              "${LS_REAL}/oflow/data/state" "${LS_REAL}/oflow/data/temp")

echo "a apagar:"
du -sh "${LARR_TARGETS[@]}" 2> /dev/null || true

${LB_YES} || die "nada apagado; repita com --yes"

rm -rf "${LARR_TARGETS[@]}"

# recria a árvore vazia
mkdir -p "${LS_REAL}"/{inbox,radar,feed} \
         "${LS_REAL}/mvol/data/dbase" "${LS_REAL}/mvol/logs" "${LS_REAL}/mrad" \
         "${LS_REAL}/nowcast/data/cappi" "${LS_REAL}/nowcast/logs" \
         "${LS_REAL}/oflow/logs" "${LS_REAL}/oflow/data"/{assets,output,state,temp}

echo "ambiente zerado: ${LS_REAL}"

# < the end >--------------------------------------------------------------------------
