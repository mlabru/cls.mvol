# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

conftest
fixtures e stubs compartilhados pela suíte de testes unitários

2026.nov  mlabru  stub do pyart (MagicMock) e backend/colormap do matplotlib
                  removidos: nenhum teste importa pyart nem matplotlib (as
                  views e rv_cappi.py saíram); o stub mascararia um import
                  real quebrado
2026.set  mlabru  stub de util.utl_dates removido (só o blend, removido, o
                  usava)
2026.set  mlabru  comentários atualizados para o layout apps/radar/, apps/cappi/

2026.jul  mlabru  initial version (Linux/Python)
"""
# < imports >--------------------------------------------------------------------------

# python library
import pathlib
import sys

# < path setup >-----------------------------------------------------------------------

# raiz deste subprojeto
PTH_ROOT = pathlib.Path(__file__).resolve().parent.parent
# diretório com os módulos da aplicação
PTH_APPS = PTH_ROOT / "apps"

# apps/ na frente do sys.path (pytest.ini já cobre isso via 'pythonpath',
# mas conftest.py pode rodar antes disso em alguns cenários de import)
if str(PTH_APPS) not in sys.path:
    sys.path.insert(0, str(PTH_APPS))

# < the end >--------------------------------------------------------------------------
