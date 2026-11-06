# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

vv_image

2026.ago  mlabru  - limpeza de diretório apagava PNGs de todos os modos
                    (glob "*.png"), agora só os do modo atual; assert de
                    config trocado por ValueError (assert some com python
                    -O); (701, 511) do resize extraído para
                    MI_IMG_WIDTH/MI_IMG_HEIGHT
                  - exceção não tratada por frame matava a QThread sem
                    emitir sgn_list_finished, deixando btn_load desabilitado
                    para sempre sem nenhuma mensagem de erro; dispatch de
                    modo duplicado (iteração + render) consolidado em um
                    único dict

2025.nov  mlabru  initial version (Linux/Python)
"""
# < imports >--------------------------------------------------------------------------

# python library
import logging
import pathlib

# PIL
from PIL import Image

# PyQt
from PyQt5 import QtCore

# < logging >--------------------------------------------------------------------------

# logger
M_LOG = logging.getLogger(__name__)
M_LOG.setLevel(logging.INFO)

# < constantes >-------------------------------------------------------------------------

# tamanho de saída dos PNGs — contrato implícito com o tamanho do lbl_image
# na UI (apps/vview/ui/wnd_main_vview_ui.py)
MI_IMG_WIDTH = 701
MI_IMG_HEIGHT = 511

# < CRadarImageWorker >----------------------------------------------------------------

class CRadarImageWorker(QtCore.QThread):
    """
    Images worker
    """
    # sinais para atualizar a interface

    # % do progresso
    sgn_update_progress = QtCore.pyqtSignal(int)
    # mensagens de texto
    sgn_message_status = QtCore.pyqtSignal(str)
    # playlist final
    sgn_list_finished = QtCore.pyqtSignal(list)

    # ---------------------------------------------------------------------------------
    def __init__(self, f_radar, fdct_config):
        """
        constructor
        """
        # logger
        M_LOG.debug(">> constructor")

        # check input
        if not fdct_config:
            raise ValueError("fdct_config não pode ser vazio/None")

        # init super class
        super().__init__()

        # radar         
        self.radar = f_radar

        # config
        self.dct_config = fdct_config

        # playlist
        self.playlist = []

    # ---------------------------------------------------------------------------------
    def run(self):
        """
        run thread
        """
        # logger
        M_LOG.debug(">> run")

        #>> limpeza inicial

        # modo de exibição 
        ls_mode = self.dct_config["mode"]

        # status
        self.sgn_message_status.emit(f"Limpando diretório de {ls_mode}...")

        # pathlib para manipulação segura de diretórios
        l_path = pathlib.Path(self.dct_config["path"])
        
        # limpeza robusta — só os PNGs do modo atual (cappi_*.png,
        # ppi_*.png, ...); um glob genérico "*.png" apagaria também os
        # frames já gerados de outros modos, forçando reprocessamento à toa
        # ao trocar de modo na GUI
        for l_arquivo in l_path.glob(f"{ls_mode.lower()}_*.png"):
            # é arquivo ?
            if l_arquivo.is_file():
                # remove o arquivo
                try: l_arquivo.unlink()
                except OSError: pass # evita travar se o arquivo estiver em uso

        # reset playlist
        self.playlist = []

        #>> definição da tarefa

        # mapeamento modo -> (iteração de valores, função de renderização).
        # a função de renderização recebe (valor_da_iteração, índice,
        # caminho_de_saída); consolida em um único lugar o que antes era um
        # if/elif duplicado (uma vez para montar a iteração, outra para
        # despachar a chamada de renderização)
        ldct_modos = {
            "CAPPI": (range(1000, 16000, 1000),
                     lambda l_val, lidx, fs_path: self.radar.cappi(
                         ff_alt_m=l_val, fs_save_path=fs_path)),
            "PPI": (range(len(self.radar.elevation_list)),
                   lambda l_val, lidx, fs_path: self.radar.ppi(
                       fi_sweep=lidx, fs_save_path=fs_path)),
            "RHI-A": (range(0, 360, 45),
                     lambda l_val, lidx, fs_path: self.radar.rhi_artificial(
                         l_val, fs_save_path=fs_path)),
            "RHI-R": (range(0, 360, 10),
                     lambda l_val, lidx, fs_path: self.radar.rhi(
                         l_val, fs_save_path=fs_path)),
        }

        # modo desconhecido ? mantém o comportamento anterior: iteração
        # vazia -> playlist vazia, sem erro
        llst_iteracao, lf_render = ldct_modos.get(ls_mode, ([], None))

        # total de iterações
        li_total = len(llst_iteracao)

        #>> loop de processamento

        # gera e redimensionamento em um único fluxo
        for lidx, l_val in enumerate(llst_iteracao):
            # status
            self.sgn_message_status.emit(f"Gerando {ls_mode} {lidx + 1} de {li_total}...")

            # nome base do arquivo — contrato de nome compartilhado com
            # vv_view.make_gif, que reparseia o prefixo via split('_')[0]
            l_img_path = l_path / f"{ls_mode.lower()}_{lidx:03d}.png"

            try:
                # despacha a renderização deste frame
                lf_render(l_val, lidx, str(l_img_path))

                # gerou a imagem ok ?
                if l_img_path.exists():
                    # redimensiona
                    with Image.open(l_img_path) as limg:
                        # novo padrão é Image.Resampling.LANCZOS (Image.Resampling.BILINEAR)
                        limg_resized = limg.resize((MI_IMG_WIDTH, MI_IMG_HEIGHT),
                                                   resample=Image.Resampling.LANCZOS)
                        # salva a imagem redimensionada
                        limg_resized.save(l_img_path, format="PNG")

                    # coloca a imagem na playlist
                    self.playlist.append(str(l_img_path))

            # uma falha em um único frame não pode matar a thread sem
            # emitir sgn_list_finished (o botão "Carregar Arquivo" ficaria
            # desabilitado para sempre, sem nenhuma mensagem de erro)
            except Exception as l_err:
                # logger
                M_LOG.exception(f"[x] falha ao gerar frame {lidx} ({ls_mode}): {l_err}")
                # status
                self.sgn_message_status.emit(f"Falha ao gerar frame {lidx + 1}: {l_err}")

            # atualiza o progresso
            li_progresso = int(((lidx + 1) / li_total) * 100)
            # emit signal
            self.sgn_update_progress.emit(li_progresso)

        # status
        self.sgn_message_status.emit(f"Processamento de {ls_mode} concluído!")

        # emit playlist
        self.sgn_list_finished.emit(self.playlist)

# < the end >--------------------------------------------------------------------------
        