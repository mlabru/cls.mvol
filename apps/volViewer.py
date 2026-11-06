# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

volViewer

2026.out  mlabru  argumento opcional: diretório de dados (.mvol), repassado
                  a CRadView (default $VOL_SYNC_DIR ou o de vol_cfg.sh)

2026.ago  mlabru  - import config removido
                  - a resolução de paths feita em CRadView._setup_paths, com
                    valores fixos
                  - título do módulo corrigido de "volView" para "volViewer"
                  - sys.exit(main()) sempre saía com 0 mesmo em caso de
                    encerramento anormal da aplicação

2026.jun  mlabru  - removido uso de sm_config.json — a GUI agora lê seus
                    caminhos do cf.G_CONFIG, como todos os demais módulos do
                    pipeline

2025.nov  mlabru  initial version (Linux/Python)
"""
# < imports >--------------------------------------------------------------------------

# python library
import logging
import pathlib
import sys

# PyQt
from PyQt5 import QtWidgets

# locals
import view.vv_view as rv

# -------------------------------------------------------------------------------------
def main() -> int:
    """
    drive app

    :returns: código de saída do Qt event loop
    """
    # logger
    logging.basicConfig(level=logging.INFO)

    # create app (QApplication consome os argumentos do Qt de sys.argv)
    l_app = QtWidgets.QApplication(sys.argv)

    # diretório de dados opcional na linha de comando
    lpth_radar = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else None

    # create main window
    lwnd_main = rv.CRadView(lpth_radar)
    # show main window
    lwnd_main.show()

    # exec app (retorna o código de saída real do event loop)
    return l_app.exec_()

# -------------------------------------------------------------------------------------
# this is the bootstrap process

if "__main__" == __name__:

    # run
    sys.exit(main())

# < the end >--------------------------------------------------------------------------
    