#!/usr/bin/env bash
#
# Centro Logístico de Simulação Meteorológica
# Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo
#
# vol_viewer.sh
# launch the interactive mvol GUI
#
# 2026.ago  mlabru  extraído para eliminar duplicação
# 2026.jun  mlabru  initial version (Bash/Linux)

# depends on: bash

set -euo pipefail

# diretório deste script (para localizar vol_common.sh)
LIB_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# funções compartilhadas
source "${LIB_DIR}/vol_common.sh"

# lança a GUI de visualização de volume
launch_app apps/volViewer.py "$@"

# < the end >--------------------------------------------------------------------------
