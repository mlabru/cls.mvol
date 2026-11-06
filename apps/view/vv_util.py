# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

vv_util

2026.out  mlabru  path_selected_file localiza o arquivo por glob
                  (*-<RRR>--<data>--<hora>.mvol): o diretório da estação tem
                  o nome completo (Santiago) e o arquivo o código (STI-250--
                  ...), então remontar o nome a partir da combo de estação
                  não achava o arquivo

2026.ago  mlabru  - file_pattern: parâmetro renomeado de fs_root_folder para
                    fpth_root_folder (era chamado sempre com pathlib.Path,
                    prefixo fs_ estava errado)
                  - file_pattern trocou rglob (recursivo) por iterdir (os
                    diretórios de estação são sempre filhos diretos);
                    files_to_play/filter_dates/filter_times removidas
                    (código morto — nenhum chamador no repositório, resíduo
                    de uma UI de seleção por intervalo de datas substituída
                    pelo fluxo atual de data/hora única); glob redundante em
                    update_hora simplificado; anotação de retorno de
                    file_pattern corrigida

2025.nov  mlabru  initial version (Linux/Python)
"""
# < imports >--------------------------------------------------------------------------

# python library
import logging
import pathlib
import re

# < logging >--------------------------------------------------------------------------

# logger
M_LOG = logging.getLogger(__name__)
M_LOG.setLevel(logging.INFO)

# -------------------------------------------------------------------------------------
def file_pattern(fpth_root_folder: pathlib.Path, fs_pattern: str) -> list[pathlib.Path]:
    """
    procura por subdiretórios que possuem exatamente o <pattern> no nome

    :note: regex: ^ indica início, [0-9]{3} são 3 números, $ indica o fim
    :note: regex: ^ indica início, [A-Z]{3} são 3 letras maiúsculas, $ indica o fim
    """
    # logger
    # M_LOG.debug(">> file_pattern")

    # base path
    lpth_base = pathlib.Path(fpth_root_folder)

    if not lpth_base.is_dir():
        # logger
        M_LOG.error(f"'{fpth_root_folder}' não é um diretório válido.")
        # quit fail
        return []

    # regex: busca o "pattern"
    l_pattern = re.compile(fs_pattern)
    
    # subdiretórios (estações são sempre filhos diretos de fs_root_folder;
    # rglob percorreria recursivamente todo o arquivo de dados .mvol à toa)
    llst_dirs = [lpth for lpth in lpth_base.iterdir()
                if lpth.is_dir() and l_pattern.match(lpth.name)]

    # ok
    return llst_dirs

# -------------------------------------------------------------------------------------
def path_selected_file(fcbx_estacao, fcbx_alcance, fcbx_datas, fcbx_horarios, fpth_base):
    """
    retorna o caminho completo (Path) e o nome do arquivo selecionado para ser
    instanciado na classe CRadar.
    """
    # logger
    # M_LOG.debug(">> path_selected_file")

    # estação selecionada
    ls_estacao = fcbx_estacao.currentText()
    ls_alcance = fcbx_alcance.currentText()
    ls_data = fcbx_datas.currentText()
    ls_horario = fcbx_horarios.currentText()

    # validação básica
    if not all([ls_estacao, ls_alcance, ls_data, ls_horario]):
        # quit fail
        return None, None

    # monta o caminho completo: path_base/ESTACAO/ALCANCE/ARQUIVO
    lpth_dir = fpth_base / ls_estacao / ls_alcance

    # localiza o arquivo (ex: Santiago/250/STI-250--2026-07-22--14-40-24.mvol)
    # -- o código da estação no nome (STI) difere do nome do diretório
    # (Santiago), então o nome não pode ser remontado a partir da combo
    llst_arqs = sorted(lpth_dir.glob(f"*-{ls_alcance}--{ls_data}--{ls_horario}.mvol"))

    if not llst_arqs:
        # logger
        M_LOG.error(f"nenhum .mvol em {lpth_dir} para {ls_data} {ls_horario}")
        # quit fail
        return None, None

    # ok
    return lpth_dir, llst_arqs[0].name

# -------------------------------------------------------------------------------------
def update_alcances(fcbx_estacao, fcbx_alcance, fpth_base):
    """
    subdiretórios de alcance (ex: 250, 100) dentro da pasta da estação
    """
    # logger
    # M_LOG.debug(">> update_alcances")

    # estação selecionada
    ls_estacao = fcbx_estacao.currentText()

    if not ls_estacao:
        # quit fail
        return

    # diretório da estação
    lpth_estacao = fpth_base / ls_estacao
    
    if not lpth_estacao.exists():
        # clear comboBox
        fcbx_alcance.clear()
        # quit fail
        return

    # subpastas dentro da estação (geralmente números como 250, 100)
    llst_alcances = [lsub.name for lsub in lpth_estacao.iterdir() if lsub.is_dir()]
    
    # clear comboBox
    fcbx_alcance.clear()
    # preenche com os alcances encontrados 
    fcbx_alcance.addItems(sorted(llst_alcances))

# -------------------------------------------------------------------------------------
def update_datas(fcbx_estacao, fcbx_alcance, flst_cbx_datas, fpth_base):
    """
    filtra os arquivos .mvol pela estação e alcance e preenche a combo de datas
    """
    # logger
    # M_LOG.debug(">> update_datas")

    # estação selecionada
    ls_estacao = fcbx_estacao.currentText()
    # alcance selecionado
    ls_alcance = fcbx_alcance.currentText()
    
    # path esperado: path_base/ESTACAO/ALCANCE/
    lpth_dir = fpth_base / ls_estacao / ls_alcance
    
    if not lpth_dir.exists():
        # para todas as combos de data... 
        for lcbx in flst_cbx_datas:
            # clear comboBox
            lcbx.clear()
        # quit fail
        return

    # set para evitar datas duplicadas
    lset_datas = set()
    
    # busca arquivos no diretório...
    for lpth_arq in lpth_dir.glob("*.mvol"):
        # split("--") transforma "CGU-250--2025-12-21--02-30-23.mvol"
        # em ["CGU-250", "2025-12-21", "02-30-23.mvol"]
        llst_partes = lpth_arq.name.split("--")

        if len(llst_partes) >= 2:
            # salva só a data ok
            lset_datas.add(llst_partes[1])

    # para todas as combos de datas... 
    for lcbx in flst_cbx_datas:
        # clear comboBox
        lcbx.clear()
        # preenche com as data encontradas
        lcbx.addItems(sorted(list(lset_datas), reverse=True))

# -------------------------------------------------------------------------------------
def update_hora(fcbx_estacao, fcbx_alcance, fcbx_data, fcbx_hora, fpth_base):
    """
    filtra os arquivos pela data selecionada e preenche os horários
    """
    # logger
    # M_LOG.debug(">> update_hora")

    # estação selecionada
    ls_estacao = fcbx_estacao.currentText()
    # alcance selecionado
    ls_alcance = fcbx_alcance.currentText()
    # data selecionada
    ls_data = fcbx_data.currentText()
    
    # path esperado: path_base/ESTACAO/ALCANCE/
    lpth_dir = fpth_base / ls_estacao / ls_alcance
    
    if not ls_data or not lpth_dir.exists():
        # clear comboBox
        fcbx_hora.clear()
        # quit fail
        return

    # lista de horas
    llst_horas = []
    
    # busca por arquivos da data... (lpth_dir já está escopado à
    # estação+alcance específicos, então repetir ls_alcance no glob é
    # redundante)
    for lpth_arq in lpth_dir.glob(f"*--{ls_data}--*.mvol"):
        # split filename
        llst_parts = lpth_arq.name.split("--")

        if len(llst_parts) >= 3:
            # remove o ".mvol" do final do horário
            ls_hora = llst_parts[2].replace(".mvol", "")
            # salva o horário na lista
            llst_horas.append(ls_hora)

    # clear comboBox
    fcbx_hora.clear()
    # preenche com horários encontrados
    fcbx_hora.addItems(sorted(llst_horas, reverse=True))

# < the end >--------------------------------------------------------------------------
