#!/usr/bin/env bash
#
# Centro Logístico de Simulação Meteorológica
# Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo
#
# tst_setup.sh
# cria o ambiente de teste com dados reais do pipeline 21.mvol -> 27.nowcast
# -> 25.oflow (+ 21.mrad), isolado de produção e do 03.dat/data compartilhado:
#
#   <raiz>/                     (padrão: 03.dat/tst)
#     env.sh      variáveis que redirecionam os três projetos (MET_ENV=test)
#     inbox/      o "servidor" do vol_sync.sh (ssh localhost), alimentado
#                 por tst_feed.py com hardlinks de TST_SRC
#     radar/      VOL_SYNC_DIR (destino do rsync)
#     mvol/       VOL_PATH: data/dbase/catalog.db (banco ÚNICO dos três), logs/
#     mrad/       RSM_PATH (RSM_DBASE_FILE = banco do mvol)
#     nowcast/    NWC_PATH: config.ini (cópia), data/cappi, logs/
#     oflow/      OFL_PATH: data/{assets,output,state,temp}, logs/ (lê o
#                 banco do mvol e os CAPPI do nowcast)
#     feed/       cursor e listas do alimentador
#
# o código continua nos repositórios; só os dados vão para a raiz.  Rodar
# de novo é seguro: recria o env.sh e o config.ini, não apaga dados (para
# isso, tst_reset.sh).
#
# uso: tst_setup.sh [raiz]          (TST_SRC sobrescreve a origem dos .mvol)
#
# 2026.out  mlabru  21.mrad sem RSM_REMOTE_*: o banco do mvol é a única fonte
#                   do mrad (sem ssh/find nos .mvol)
# 2026.out  mlabru  27.nowcast (era 25.nowcast, renumerado): TST_NWC_DIR
#                   apontava para um diretório inexistente
#
# 2026.out  mlabru  nowcast: NWC_PATH (antes NWC_HOME), NWC_DBASE_FILE e
#                   NWC_CAPPI_DIR no env.sh; o config.ini é copiado sem
#                   alteração (antes era reescrito com sed)
#
# 2026.out  mlabru  25.oflow (nowcast por optical flow) incluído: bloco OFL_*
#                   no env.sh e árvore oflow/ (assets com o GIF de aviso)
#
# 2026.out  mlabru  initial version (Linux/Bash)

# depends on: bash, ssh (por chave, para localhost), rsync, python3

set -euo pipefail

# < configuração >---------------------------------------------------------------------

# tst_env/, 21.mvol/04.dvl e a raiz met/ dos projetos
TST_ENV_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
TST_MVOL_DIR="$( cd "${TST_ENV_DIR}/.." && pwd )"
TST_MET_DIR="$( cd "${TST_MVOL_DIR}/../.." && pwd )"

# projetos irmãos
TST_MRAD_DIR="${TST_MET_DIR}/21.mrad/04.dvl"
TST_NWC_DIR="${TST_MET_DIR}/27.nowcast/04.dvl"
TST_OFL_DIR="${TST_MET_DIR}/25.oflow/04.dvl"

# raiz do ambiente e origem dos .mvol reais
TST_ROOT="$(realpath -m "${1:-${TST_MET_DIR}/03.dat/tst}")"
TST_SRC="$(realpath -m "${TST_SRC:-${TST_MET_DIR}/03.dat/lmc15.ori}")"

# < funções >--------------------------------------------------------------------------

die() { echo "[error]: $*" >&2; exit 1; }

# < main >-----------------------------------------------------------------------------

for ls_dir in "${TST_MRAD_DIR}" "${TST_NWC_DIR}" "${TST_OFL_DIR}" "${TST_SRC}"; do
    [ -d "${ls_dir}" ] || die "diretório não encontrado: ${ls_dir}"
done

# a origem nunca pode ficar dentro do ambiente (tst_reset.sh apagaria)
case "${TST_SRC}/" in
    "${TST_ROOT}/"*) die "a origem ${TST_SRC} está dentro da raiz ${TST_ROOT}" ;;
esac

mkdir -p "${TST_ROOT}"/{inbox,radar,feed} \
         "${TST_ROOT}/mvol/data/dbase" "${TST_ROOT}/mvol/logs" \
         "${TST_ROOT}/mrad" \
         "${TST_ROOT}/nowcast/data/cappi" "${TST_ROOT}/nowcast/logs" \
         "${TST_ROOT}/oflow/logs" \
         "${TST_ROOT}/oflow/data"/{assets,output,state,temp}

# GIF de aviso que o ofl_common.sh::run_makeGIF() copia quando um backend
# falha (em produção vem de data/assets do OFL_PATH)
for ls_gif in no_cast.gif; do
    ls_orig="$(realpath -e "${TST_OFL_DIR}/data/assets/${ls_gif}" 2> /dev/null)" || \
        die "${ls_gif} não encontrado em ${TST_OFL_DIR}/data/assets"
    cp -u "${ls_orig}" "${TST_ROOT}/oflow/data/assets/"
done

# hardlinks exigem o mesmo sistema de arquivos
[ "$(stat -c %d "${TST_SRC}")" = "$(stat -c %d "${TST_ROOT}/inbox")" ] || \
    die "${TST_SRC} e ${TST_ROOT} estão em sistemas de arquivos diferentes (hardlink impossível)"

command -v rsync > /dev/null || die "rsync não instalado"

# o vol_sync.sh roda com BatchMode: sem chave, falharia em todo ciclo
ssh -o BatchMode=yes -o ConnectTimeout=5 localhost true 2> /dev/null || \
    die "ssh localhost sem senha falhou; autorize a própria chave:
       cat ~/.ssh/id_ed25519.pub >> ~/.ssh/authorized_keys"

# env.sh: tudo que os três projetos leem do ambiente
cat > "${TST_ROOT}/env.sh" <<EOF
# gerado por ${TST_ENV_DIR}/tst_setup.sh em $(date -u '+%F %T')Z -- não editar
# uso: source ${TST_ROOT}/env.sh

# trava (vol_cfg.sh, rsm_cfg.sh, nwc_*.sh): nada fora de MET_TST_ROOT,
# servidor só localhost
export MET_ENV=test
export MET_TST_ROOT="${TST_ROOT}"

# código e origem dos dados
export TST_ENV_DIR="${TST_ENV_DIR}"
export TST_MVOL_DIR="${TST_MVOL_DIR}"
export TST_MRAD_DIR="${TST_MRAD_DIR}"
export TST_NWC_DIR="${TST_NWC_DIR}"
export TST_OFL_DIR="${TST_OFL_DIR}"
export TST_SRC="${TST_SRC}"

# 21.mvol (vol_cfg.sh)
export VOL_SYNC_DIR="${TST_ROOT}/radar"
export VOL_PATH="${TST_ROOT}/mvol"
export VOL_DBASE_FILE="${TST_ROOT}/mvol/data/dbase/catalog.db"
export VOL_REMOTE_USER="${USER}"
export VOL_REMOTE_IP=localhost
export VOL_REMOTE_DIR="${TST_ROOT}/inbox"

# 21.mrad (rsm_cfg.sh): o MESMO banco do mvol, sua única fonte de dados
export RSM_PATH="${TST_ROOT}/mrad"
export RSM_DBASE_FILE="${TST_ROOT}/mvol/data/dbase/catalog.db"

# 27.nowcast (nwc_cfg.sh): config.ini, logs e data/ em NWC_PATH; banco do
# mvol (sobrepõe o [paths] do config.ini, que é copiado sem alteração)
export NWC_PATH="${TST_ROOT}/nowcast"
export NWC_DBASE_FILE="${TST_ROOT}/mvol/data/dbase/catalog.db"
export NWC_CAPPI_DIR="${TST_ROOT}/nowcast/data/cappi"

# 25.oflow (ofl_cfg.sh): dados em OFL_PATH; lê o banco do mvol e os CAPPI do
# nowcast; sem filtro de idade (o replay tem targets de meses atrás) e com
# verificação contra o target observado
export OFL_PATH="${TST_ROOT}/oflow"
export OFL_CATALOG_DB="${TST_ROOT}/mvol/data/dbase/catalog.db"
export OFL_CAPPI_DIR="${TST_ROOT}/nowcast/data/cappi"
export OFL_AGE_MAX_SECS=0
export OFL_TIMEOUT_SECS=300
export OFL_VERIFY=true
EOF

# config.ini do nowcast: o do repositório, sem alteração -- os caminhos vêm
# do env.sh (NWC_DBASE_FILE, NWC_CAPPI_DIR) e os relativos que sobram
# (log_dir) resolvem dentro de NWC_PATH
cp "${TST_NWC_DIR}/config.ini" "${TST_ROOT}/nowcast/config.ini"

echo "ambiente pronto em ${TST_ROOT}"
echo "origem: ${TST_SRC} ($(find "${TST_SRC}" -name '*.mvol' | wc -l) .mvol)"
echo "próximo passo: ${TST_ENV_DIR}/tst_cycle.sh --hours 2"

# < the end >--------------------------------------------------------------------------
