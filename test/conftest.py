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
import os
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

# < ambiente cls >---------------------------------------------------------------------

# a suíte não depende do cls.env de quem a roda (~/.config/cls/cls.env): os
# scripts shell testados herdam este ambiente e não carregam nada de lá
os.environ["CLS_ENV_FILE"] = os.devnull

# cls_common.sh: CLS_LIB do ambiente ou, no checkout de desenvolvimento, o
# repo cls.common irmão (<raiz>/cls.common, com o projeto em
# <raiz>/<nn>.<proj>/cls.<proj>)
os.environ.setdefault("CLS_LIB", str(pathlib.Path(__file__).resolve().parents[3]
                                     / "cls.common" / "bash"))

# pacote Python comum (cls_common): CLS_PYLIB do ambiente ou o cls.common
# irmão -- no sys.path desta suíte e no PYTHONPATH dos subprocessos (os
# scripts shell o recebem de novo por cls_setup_pythonpath, sem repetir)
os.environ.setdefault("CLS_PYLIB", str(pathlib.Path(__file__).resolve().parents[3]
                                       / "cls.common" / "python"))
if os.environ["CLS_PYLIB"] not in sys.path:
    sys.path.insert(0, os.environ["CLS_PYLIB"])
if os.environ["CLS_PYLIB"] not in os.environ.get("PYTHONPATH", "").split(":"):
    os.environ["PYTHONPATH"] = ":".join(filter(None, (os.environ["CLS_PYLIB"],
                                                      os.environ.get("PYTHONPATH"))))

# < the end >--------------------------------------------------------------------------
