# Centro Logístico de Simulação Meteorológica
# Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo
#
# vol_common.sh
# funções compartilhadas pelos scripts vol_*.sh:
# - log: logger em UTC com rotação (sobre met_log, de met_common.sh);
# - launch_app: roda um app Python do projeto (virtualenv, PYTHONPATH e
#   banners de início/fim).
# check_log_size também fica disponível (vem de met_common.sh).
#
# 2026.out  mlabru  refatoração para legibilidade: launch_app sem variável
#                   supérflua; comentários atualizados
#
# 2026.out  mlabru  check_log_size e o corpo do log() vêm do met_common.sh
#                   (comum aos projetos met); o horário do log() passa a
#                   ser UTC, como os logs Python
#
# 2026.set  mlabru  log() (vol_downloader.sh) extraída para eliminar
#                   duplicação -- compartilhada agora com vol_sync.sh
#
# 2026.ago  mlabru  check_log_size (vol_downloader.sh/vol_blender.sh)
#                   extraída para eliminar duplicação
#
# 2026.jun  mlabru  initial version (Linux/Bash)
#
# depends on: bash, met_common.sh, GI_LOG_MAX_SIZE (vol_cfg.sh) para check_log_size,
#             VOL_LOG_APP/VOL_LOG_ERR (definidas por cada script) para log()
# shellcheck shell=bash

# check_log_size e met_log (met_common.sh, symlink para 04.dvl/bash, comum
# aos projetos met)
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/met_common.sh"

# < log >------------------------------------------------------------------------------
#
# logger com timestamp UTC e rotação (met_log): grava em VOL_LOG_APP (tee,
# ecoando também em stderr) -- nível ([info]/[warn]/[error]) é convenção do
# chamador, embutida no início de $*, não um parâmetro separado
#
# depends on: VOL_LOG_APP, VOL_LOG_ERR (definidas por cada script antes de
# chamar log())
#
# uso: log "[info]: mensagem"
#
log()
{
    met_log "${VOL_LOG_APP}" "${VOL_LOG_ERR}" "$@"

} # log

# < launch_app >-----------------------------------------------------------------------
#
# resolve o diretório do projeto (a partir de quem chamou este arquivo),
# ativa o virtualenv (se existir), roda o script Python informado repassando
# os argumentos restantes, e desativa o virtualenv ao final
#
# uso: launch_app <script_relativo_ao_projeto> [args...]
#
launch_app()
{
    # script python a executar (caminho relativo à raiz do projeto)
    local ls_script="$1"
    shift

    # diretório do projeto -- calculado a partir do arquivo que chamou esta
    # função (ex.: vol_viewer.sh), não deste próprio arquivo
    local ls_project_dir
    ls_project_dir="$( cd "$( dirname "${BASH_SOURCE[1]}" )" && pwd )"

    # muda para o diretório do projeto
    cd "${ls_project_dir}" || exit 1

    # ativa o virtualenv apenas se ele existir -- evita quebrar (set -e) em
    # máquinas sem venv configurado
    [ -f ~/.venv/bin/activate ] && source ~/.venv/bin/activate

    # nome do app para o banner (nome base do script, sem extensão)
    local ls_app_name
    ls_app_name="$(basename "${ls_script}" .py)"

    echo
    echo "========================================================="
    echo "${ls_app_name} starts @ $(date)"
    echo

    # módulos precisam estar em PYTHONPATH pois apps/ não é um package
    PYTHONPATH="${ls_project_dir}/apps" python3 "${ls_script}" "$@"

    # desativa o virtualenv, se foi ativado
    type deactivate &>/dev/null && deactivate

    echo
    echo "${ls_app_name} finalizado @ $(date)"
    echo "========================================================="
    echo

} # launch_app

# < the end >--------------------------------------------------------------------------
