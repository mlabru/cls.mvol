# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

conftest
fixtures e stubs compartilhados pela suíte de testes unitários

2026.set  mlabru  stub de util.utl_dates removido (só o blend, removido, o
                  usava)
2026.set  mlabru  comentários atualizados para o layout apps/radar/, apps/cappi/

2026.jul  mlabru  initial version (Linux/Python)
"""
# < imports >--------------------------------------------------------------------------

# python library
import pathlib
import sys
from unittest.mock import MagicMock

# < path setup >-----------------------------------------------------------------------

# raiz deste subprojeto (05.radar/02.src)
PTH_ROOT = pathlib.Path(__file__).resolve().parent.parent
# diretório com os módulos da aplicação
PTH_APPS = PTH_ROOT / "apps"

# apps/ na frente do sys.path (pytest.ini já cobre isso via 'pythonpath',
# mas conftest.py pode rodar antes disso em alguns cenários de import)
if str(PTH_APPS) not in sys.path:
    sys.path.insert(0, str(PTH_APPS))

# < matplotlib backend >-----------------------------------------------------------------
# força um backend não-interativo antes que qualquer módulo sob teste importe
# matplotlib.pyplot (ex: view/vv_radar.py), evitando falha em ambiente
# sem display (headless/CI)

import matplotlib
matplotlib.use("Agg")

# < pyart stub >-------------------------------------------------------------------------
# cappi/cp_core.py e radar/rd_pyart_adapter.py fazem 'import pyart' (radar/ e
# cappi/ são pacotes locais relativos a apps/, não dependências externas). O pacote
# 'pyart' não está instalado neste ambiente. Os testes aqui não exercitam
# código que efetivamente chama a API do Py-ART, então um MagicMock é
# suficiente para permitir a importação do módulo.

if "pyart" not in sys.modules:
    sys.modules["pyart"] = MagicMock(name="pyart")

    # importar o Py-ART de verdade registra colormaps customizados no
    # matplotlib (ex: "NWSRef", usado por rv_cappi.py). Como o import está
    # stubado, replica-se aqui esse único efeito colateral relevante para
    # os testes que chamam contourf/imshow diretamente com cmap="NWSRef"
    if "NWSRef" not in matplotlib.colormaps:
        matplotlib.colormaps.register(matplotlib.colormaps["turbo"], name="NWSRef")

# < the end >--------------------------------------------------------------------------
