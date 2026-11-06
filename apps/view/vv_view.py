# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

vv_view

2026.out  mlabru  - GUI voltou a abrir: import radar.rd_radar (removido)
                    trocado por view.vv_radar (CRadar restaurado) e
                    _setup_paths não usa mais cf.G_CONFIG (NameError, cf
                    nunca importado)
                  - diretório de dados: argumento fpth_radar (linha de
                    comando do volViewer) > $VOL_SYNC_DIR >
                    /mnt/usr.L02/$USER/radar (default de vol_cfg.sh);
                    imagens em data/temp/viewer deste checkout
                  - estações: qualquer subdiretório (a árvore usa nomes
                    completos, ex: Santiago/, não mais ^[A-Z]{3}$)
                  - Open folder troca o diretório de dados e repopula as
                    estações (antes setava pth_work, que nada lia); Open
                    file carrega o .mvol escolhido (antes só logava o nome)
                  - pth_work / data_absolute_path removidos (sem leitor)

2026.set  mlabru  import radar.rv_radar -> radar.rd_radar (módulo renomeado)

2026.ago  mlabru  - import config removido _setup_paths — este ambiente não
                    tem o pacote config.py disponível
                  - pth_radar / pth_work / pth_images voltam a ser paths
                    absolutos fixos deste checkout (data / raw, data / cappi
                    -- symlink para 27.nowcast / 04.dvl / data / cappi -- e
                    data / output)
                  - título do módulo corrigido de "rv_view" para "vv_view"
                  - botões de navegação disparavam show_image em duplicidade
                    (lambda direta + sinal de cbx_val)
                  - combos de campo / modo / valor agora travados durante
                    rebuild_images (evita corrida com CRadarImageWorker
                    mutando self.radar concorrentemente)
                  - referência morta a set_file removida
                  - __init__ quebrado em métodos privados coesos
                  - display_1 indexava mensagens por número mágico, agora
                    usa constantes nomeadas
                  - docstring de make_gif corrigida (estava copiada de
                    make_connections)
                  - SAfile renomeado para ls_file (notação húngara)
                  - pth_work agora sempre pathlib.Path (era str vindo do
                    QFileDialog em set_path)
                  - botão "Gerar 3D" desabilitado com tooltip — render3D é
                    stub e rv_render.py foi movido para apps / .bkp /
                  - import ui.wnd_main_rview_ui corrigido para
                    rview.ui.wnd_main_rview_ui — com PYTHONPATH=apps (setup
                    documentado em rad_view.sh), 'ui' não é resolvível como
                    pacote de topo (vive em apps / rview / ui / )

2026.jul  mlabru  - load_file() lia atributos inexistentes em CRadar (Count,
                    nsweeps, NumberOfReflectivity / StepOfReflectivity /
                    StartOfReflectivity) — corrigido para os nomes reais
                    (n_rays, n_sweeps, n_reflectivity_gates /
                    step_of_reflectivity / start_of_reflectivity), o que
                    fazia load_file() sempre falhar com AttributeError ao
                    carregar qualquer arquivo real
                  - self.radar inicializado em __init__ (evita
                    AttributeError ao trocar modo / campo antes de carregar
                    um arquivo)
                  - open_file / set_path referenciavam nomes inexistentes
                    (mainWindow, number_dic), mascarados por bare except
                  - bare except substituídos por except Exception com log
                  - make_gif não abortava quando o usuário cancelava o
                    diálogo de formato
                  - rebuild_images agora ignora chamadas concorrentes
                    enquanto um worker anterior ainda está rodando
                  - finish_work resincroniza o índice exibido com a nova
                    playlist
                  - código morto removido (set_file comentado, UI de
                    velocidade comentada, import datetime não usado, asserts
                    inalcançáveis)
                  - removido sm_config.json: CRadView() não recebe mais um
                    dict de config — lê radar_path (via
                    cf.G_CONFIG.raw_dirs[0]), work_path
                    (cf.G_CONFIG.cappi_dir.parent) e images_path
                    (cf.G_CONFIG.images_path) direto do cf.G_CONFIG, como os
                    demais módulos do pipeline.

2025.nov  mlabru  initial version (Linux/Python)
"""
# < imports >--------------------------------------------------------------------------

# python library
import logging
import os
import pathlib
import subprocess
import time

# PyQt
from PyQt5 import QtCore, QtGui, QtWidgets

# view
import view.ui.wnd_main_vview_ui as wm

# model
import view.vv_image as iw
import view.vv_radar as rd
import view.vv_util as ut

# < logging >--------------------------------------------------------------------------

# logger
M_LOG = logging.getLogger(__name__)
M_LOG.setLevel(logging.INFO)

# < constantes >-----------------------------------------------------------------------

# índices das mensagens de status pré-definidas em CRadView.display_1() —
# nomeadas para não quebrar silenciosamente os chamadores se a lista de
# mensagens for reordenada
MI_MSG_LENDO_DADOS = 0
MI_MSG_DADOS_SELECIONADOS = 1
MI_MSG_CAMINHO_TRABALHO_SELECIONADO = 7

# diretório de dados default — mesmo default de VOL_SYNC_DIR em vol_cfg.sh
# (destino do vol_sync.sh, árvore <Estação>/<RRR>/<EEE>-<RRR>--...mvol)
MS_RADAR_DIR_DEFAULT = f"/mnt/usr.L02/{os.environ.get('USER', '')}/radar"

# diretório das imagens geradas (PNGs de vv_image) — intermediários
# descartáveis, em data/temp (VOL_TEMP) deste checkout
MPTH_IMAGES = pathlib.Path(__file__).resolve().parents[2] / "data" / "temp" / "viewer"

# < CRadView >-------------------------------------------------------------------------

class CRadView(QtWidgets.QMainWindow):
    """
    CRadView
      - CAPPI (Constant Altitude Plan Position Indicator)
      - PPI (Plan Position Indicator)
      - RHI (Range Height Indicator)
    """
    # ---------------------------------------------------------------------------------
    def __init__(self, fpth_radar: pathlib.Path = None):
        """
        constructor

        :param fpth_radar: diretório de dados (.mvol); None usa $VOL_SYNC_DIR
                           ou MS_RADAR_DIR_DEFAULT
        """
        # logger
        M_LOG.debug(">> constructor")

        # init super class
        super().__init__()

        # setup UI
        self._setup_ui()

        # dados do radar carregado / worker de geração de imagens
        self._init_state()

        # paths de dados/imagens
        self._setup_paths(fpth_radar)

        # popula a comboBox de estações e força a primeira seleção
        self._setup_stations()

        # estado de playback (playlist, índice, modo/campo/sweep atuais)
        self._init_playback_state()

        # make connections
        self.make_connections()

        # cria o timer para a animação
        self._setup_timer()

    # ---------------------------------------------------------------------------------
    def _setup_ui(self):
        """
        cria e instala a UI gerada (.ui -> _ui.py)
        """
        # logger
        M_LOG.debug(">> _setup_ui")

        # create main window
        self._ui = wm.Ui_mainWindow()

        # setup UI
        self._ui.setupUi(self)

        # renderização 3D é um stub (ver CRadar.render3D em vv_radar.py; a
        # implementação VTK foi movida para apps/.bkp/rv_render.py) — o
        # botão fica desabilitado em vez de responder a clique sem fazer
        # nada visível ao operador
        self._ui.btn_3d.setEnabled(False)
        self._ui.btn_3d.setToolTip("Renderização 3D temporariamente desativada")

    # ---------------------------------------------------------------------------------
    def _init_state(self):
        """
        inicializa o estado de radar/worker carregado
        """
        # logger
        M_LOG.debug(">> _init_state")

        # dados do radar carregado — None até load_file() ser chamado. Os
        # combos de modo/campo já vêm populados pela UI antes de qualquer
        # carregamento, então handlers como on_mode_changed/on_field_changed
        # precisam checar isso antes de acessar self.radar
        self.radar = None

        # worker de geração de imagens em background — None até a primeira
        # chamada de rebuild_images()
        self.worker = None

    # ---------------------------------------------------------------------------------
    def _setup_paths(self, fpth_radar: pathlib.Path = None):
        """
        resolve os paths de dados/imagens

        :param fpth_radar: diretório de dados; None usa $VOL_SYNC_DIR ou
                           MS_RADAR_DIR_DEFAULT
        """
        # logger
        M_LOG.debug(">> _setup_paths")

        # radar path — argumento > $VOL_SYNC_DIR > default de vol_cfg.sh
        self.pth_radar = pathlib.Path(fpth_radar or
                                      os.environ.get("VOL_SYNC_DIR") or
                                      MS_RADAR_DIR_DEFAULT)
        # images path (vv_image grava aqui, então precisa existir)
        self.pth_images = MPTH_IMAGES
        self.pth_images.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------------------------
    def _setup_stations(self):
        """
        popula a comboBox de estações e força a primeira seleção
        """
        # logger
        M_LOG.debug(">> _setup_stations")

        # bloqueia sinais para o clear()/addItem() não dispararem
        # on_estacao_changed a cada item (chamado uma vez no final)
        self._ui.cbx_station.blockSignals(True)
        self._ui.cbx_station.clear()

        # find stations folders (nomes completos, ex: Santiago; ignora
        # ocultos como .bkp)...
        for l_dir in sorted(ut.file_pattern(self.pth_radar, r"^[^.]")):
            # save on stations comboBoxes
            self._ui.cbx_station.addItem(l_dir.name)

        # libera sinais
        self._ui.cbx_station.blockSignals(False)

        # força a primeira seleção
        self.on_estacao_changed()

    # ---------------------------------------------------------------------------------
    def _init_playback_state(self):
        """
        inicializa o estado de playback (playlist, índice, modo/campo/sweep)
        """
        # logger
        M_LOG.debug(">> _init_playback_state")

        # playlist ativa
        self.playlist_atv = []

        # index
        self.image_ndx = 0

        # current mode
        self.mode = "PPI"
        # current field
        self.field = "corrected_reflectivity"
        # current sweep
        self.sweep = 0

    # ---------------------------------------------------------------------------------
    def _setup_timer(self):
        """
        cria o timer usado para tocar a animação
        """
        # logger
        M_LOG.debug(">> _setup_timer")

        # cria o timer para a animação
        self.timer_ani = QtCore.QTimer()
        self.timer_ani.setInterval(self._ui.spn_vel.value())
        self.timer_ani.timeout.connect(self.step_anima)

    # ---------------------------------------------------------------------------------
    def display_1(self, fi_ordem):
        """
        exibe na área de eventos uma mensagem de status pré-definida,
        indexada por fi_ordem
        """
        # logger
        M_LOG.debug(">> display_1")

        info = ["Lendo dados...", "Dados selecionados", "Processando dados...",
                "Processamento concluído", "Desenhando imagem...", "Desenho concluído",
                "Inicializando dados...", "Caminho de trabalho selecionado",
                "", "", "", "", "", "", "", "", "", "", "", "", ]

        self.update_logger(info[fi_ordem])

    # ---------------------------------------------------------------------------------
    def finish_work(self, flst_playlist: list):
        """
        finish worker
        """
        # logger
        M_LOG.debug(">> finish_work")

        # habilita load button e os combos travados em rebuild_images()
        self._ui.btn_load.setEnabled(True)
        self._ui.cbx_fields.setEnabled(True)
        self._ui.cbx_modes.setEnabled(True)
        self._ui.cbx_val.setEnabled(True)

        # salva a playlist
        self.playlist_atv = flst_playlist

        if self.playlist_atv:
            # resincroniza o índice exibido com a nova playlist (evita
            # index_add/index_reduce/step_anima operarem com um índice de
            # uma playlist anterior, potencialmente maior)
            self.image_ndx = 0

            # bloqueia sinais para não disparar on_value_changed prematuramente
            self._ui.cbx_val.blockSignals(True)
            self._ui.cbx_val.setCurrentIndex(0)
            self._ui.cbx_val.blockSignals(False)

            # show first image
            self.show_image(0)
            # atualiza registro de eventos
            self.update_logger(f"Playlist pronta para exibição! ({len(self.playlist_atv)})")

    # ---------------------------------------------------------------------------------
    def index_add(self):
        """
        increment index
        """
        # logger
        M_LOG.debug(">> index_add")

        # increment index
        self.image_ndx += 1

        # wrap-around ?
        if self.image_ndx == len(self.playlist_atv):
            # reset index
            self.image_ndx = 0

        # ajusta comboxBox
        self._ui.cbx_val.setCurrentIndex(self.image_ndx)

    # ---------------------------------------------------------------------------------
    def index_end(self):
        """
        index to end of list
        """
        # logger
        M_LOG.debug(">> index_end")

        # index to end of list
        self.image_ndx = len(self.playlist_atv) - 1

        # ajusta comboxBox
        self._ui.cbx_val.setCurrentIndex(self.image_ndx)

    # ---------------------------------------------------------------------------------
    def index_reduce(self):
        """
        decrement index
        """
        # logger
        M_LOG.debug(">> index_reduce")

        # check ok
        if self.image_ndx > 0:
            # decrement index
            self.image_ndx -= 1

            # ajusta comboxBox
            self._ui.cbx_val.setCurrentIndex(self.image_ndx)

    # ---------------------------------------------------------------------------------
    def index_zero(self):
        """
        reset index
        """
        # logger
        M_LOG.debug(">> index_zero")

        # reset index
        self.image_ndx = 0

        # ajusta comboxBox
        self._ui.cbx_val.setCurrentIndex(self.image_ndx)

    # ---------------------------------------------------------------------------------
    def load_file(self):
        """
        process data
        """
        # logger
        M_LOG.debug(">> load_file")

        # path e nome do arquivo seleciondo
        lpth_path, ls_arquivo = ut.path_selected_file(self._ui.cbx_station,
                                                      self._ui.cbx_range,
                                                      self._ui.cbx_date,
                                                      self._ui.cbx_time,
                                                      self.pth_radar)
        if not ls_arquivo:
            # logger
            self.update_logger("nenhum arquivo .mvol selecionado.")
            # quit fail
            return

        # carrega e exibe
        self._load_radar_file(lpth_path, ls_arquivo)

    # ---------------------------------------------------------------------------------
    def _load_radar_file(self, fpth_path: pathlib.Path, fs_arquivo: str):
        """
        carrega um arquivo .mvol e preenche a tela (comum a load_file e
        open_file)

        :param fpth_path: diretório do arquivo
        :param fs_arquivo: nome do arquivo
        """
        # logger
        M_LOG.debug(">> _load_radar_file")

        # progress bar
        self._ui.pgr_load.setValue(10)
        # logger
        self.update_logger(f"carregando {fs_arquivo}...")

        try:
            # carrega dados do arquivo mvol (CRadar.__init__ sempre levanta
            # exceção em caso de falha — nunca retorna um objeto inválido)
            self.radar = rd.CRadar(fpth_path, fs_arquivo)

        # em caso de erro,...
        except Exception as l_err:
            # logger
            M_LOG.exception(f"[x] _load_radar_file: {l_err}")
            # feedback ao usuário
            self.update_logger(f"falha ao carregar {fs_arquivo}: {l_err}")
            # progress bar
            self._ui.pgr_load.setValue(0)
            # quit fail
            return

        # update progress bar
        self._ui.pgr_load.setValue(60)

        #>> preenche dados para visualização

        # metadados GAMIC (.get: nem todo arquivo traz todas as chaves)
        ldct_meta = self.radar.metadata

        # estação
        self._ui.lbl_station.setText(str(ldct_meta.get("site_name", "")))
        # data
        self._ui.lbl_date.setText(str(ldct_meta.get("gamic_date", "")))
        # container
        self._ui.lbl_container.setText(f"{ldct_meta.get('original_container', '')}"
                                       f" v.{ldct_meta.get('gamic_version', '')}")
        # template
        self._ui.lbl_template.setText(str(ldct_meta.get("template_name", "")))
        # localização
        self._ui.lbl_local.setText(f"{self.radar.latitude} {self.radar.longitude}")
        self._ui.lbl_alt.setText(f"{self.radar.altitude}")
        # range
        self._ui.lbl_range.setText(str(int(self.radar.range)))

        # número de raios
        self._ui.lbl_nrays.setText(str(int(self.radar.n_rays)))
        # número de varreduras
        self._ui.lbl_nsweeps.setText(str(int(self.radar.n_sweeps)))
        # modo de varredura
        self._ui.lbl_scan_mode.setText(str(self.radar.vcp))
        # quantidade de elevações
        self._ui.lbl_ele_no.setText(str(len(self.radar.elevation_list)))

        # reflectividade (distâncias em metros).  n_reflectivity_gates/
        # step_of_reflectivity/start_of_reflectivity agora são escalares em
        # CRadar (rv_radar.py) — antes eram arrays O(n_rays) só lidos em [0]
        self._ui.lbl_ref_number.setText(str(self.radar.n_reflectivity_gates))
        self._ui.lbl_ref_step.setText(str(self.radar.step_of_reflectivity))
        self._ui.lbl_ref_start.setText(str(self.radar.start_of_reflectivity))

        # update progress bar
        self._ui.pgr_load.setValue(80)

        # build fields comboBox
        self.process_fields()

        # update progress bar
        self._ui.pgr_load.setValue(90)

        # build mode (CAPPI, PPI or RHI) playlist
        self.on_mode_changed()

        # update progress bar
        self._ui.pgr_load.setValue(100)

    # ---------------------------------------------------------------------------------
    def make_connections(self):
        """
        connect signals to slots
        """
        # logger
        M_LOG.debug(">> make_connections")

        #>> menu

        # open folder
        self._ui.actionOpen_folder.triggered.connect(self.set_path)
        # open file
        self._ui.actionopen.triggered.connect(lambda: self.display_1(MI_MSG_LENDO_DADOS))
        self._ui.actionopen.triggered.connect(self.open_file)

        #>> dados únicos / seleção de dados

        # muda a estação -> atualiza alcances
        self._ui.cbx_station.currentIndexChanged.connect(self.on_estacao_changed)
        # muda o alcance -> atualiza datas
        self._ui.cbx_range.currentIndexChanged.connect(self.on_alcance_changed)
        # muda a data -> atualiza horários
        self._ui.cbx_date.currentIndexChanged.connect(self.on_date_changed)

        # carrega arquivo
        self._ui.btn_load.clicked.connect(self.load_file)

        # gera imagem 3D
        self._ui.btn_3d.clicked.connect(self.plot_3d)

        #>> dados únicos / tab imagem

        # item de exibição
        self._ui.cbx_fields.currentIndexChanged.connect(self.on_field_changed)
        # modo de exibição
        self._ui.cbx_modes.currentIndexChanged.connect(self.on_mode_changed)
        # sweep
        self._ui.cbx_val.currentIndexChanged.connect(self.on_value_changed)

        #>> animação / play control

        # navegação: index_zero/index_end/index_reduce/index_add já chamam
        # cbx_val.setCurrentIndex(), que dispara currentIndexChanged ->
        # on_value_changed -> show_image(). uma lambda extra chamando
        # show_image() aqui duplicava a renderização quando o índice mudava
        # (e exibia de forma inconsistente quando não mudava — ex.: já no
        # primeiro/último item)

        # 1st imagem -> reset index
        self._ui.btn_first.clicked.connect(self.index_zero)
        # última imagem -> index to maximum
        self._ui.btn_last.clicked.connect(self.index_end)
        # imagem anterior -> decrementa index
        self._ui.btn_prev.clicked.connect(self.index_reduce)
        # próxima imagem -> incrementa index
        self._ui.btn_next.clicked.connect(self.index_add)

        # play animation
        self._ui.btn_play.clicked.connect(self.play_anima)
        # stop animation
        self._ui.btn_stop.clicked.connect(self.stop_anima)

        # anima velocity
        self._ui.spn_vel.valueChanged.connect(self.on_velocity_changed)
        # make GIF
        self._ui.btn_gif.clicked.connect(self.make_gif)

    # ---------------------------------------------------------------------------------
    def make_gif(self):
        """
        exporta a playlist ativa como GIF ou MP4 via ffmpeg, perguntando o
        formato ao usuário
        """
        # logger
        M_LOG.debug(">> make_gif")

        # clear to go
        if not self.playlist_atv:
            # quit fail
            return
        # path of first anime
        l_anime_path = pathlib.Path(self.playlist_atv[0])
        # extract mode from first anime
        ls_prfx = l_anime_path.name.split('_')[0]
        # path dos animes
        ls_input_path = os.path.join(l_anime_path.parent, f"{ls_prfx}_%03d.png")
        # path dos animes
        ls_output_path = os.path.join(l_anime_path.parent, f"{ls_prfx}_out")

        # converte o valor da spinBox (ms) para FPS (500ms são 2 FPS)
        li_fps = max(1, int(1000 / self.timer_ani.interval()))

        # tipos de formatos
        ltpl_formatos = ("GIF", "MP4")
        # abre um diálogo simples para escolher o formato
        ls_fmt, lv_ok = QtWidgets.QInputDialog.getItem(self, "Exportar",
                                                       "Escolha o formato:",
                                                       ltpl_formatos, 0, False)
        # usuário cancelou o diálogo ?
        if not lv_ok:
            # logger
            self.update_logger("exportação cancelada pelo usuário.")
            # quit fail
            return

        # monta o commando
        llst_default = ["ffmpeg",
                        "-y",                         # sobrescreve já existir
                        "-i", ls_input_path,
                        "-framerate", str(li_fps)]    # 1 FPS

        # formato GIF ?
        if "GIF" == ls_fmt:
            # alta qualidade
            ls_vf = "split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse" 

            # monta o commando 
            llst_fmt = ["-vf", ls_vf,               # alta qualidade
                        ls_output_path + ".gif"]
        # senão, MP4
        else:
            # qualidade
            ls_vf = "pad=ceil(iw/2)*2:ceil(ih/2)*2"
            # monta o commando 
            llst_fmt = ["-c:v", "libx264",
                        "-pix_fmt", "yuv420p",
                        "-vf", ls_vf,
                        ls_output_path + ".mp4"]
        
        try:
            # monta o comando
            llst_command = llst_default + llst_fmt
            # cria o GIF/MP4 usando ffmpeg
            subprocess.run(llst_command, check=True)
            # logger
            self.update_logger(f"{ls_fmt} '{ls_prfx}_output' gerado com sucesso!")

        # em caso de erro,...
        except subprocess.CalledProcessError as l_err:
            # logger
            self.update_logger(f"ffmpeg failed with error: {l_err}")

    # ---------------------------------------------------------------------------------
    def on_alcance_changed(self):
        """
        processa alteração no alcance
        """
        # logger
        M_LOG.debug(">> on_alcance_changed")

        # combo vazia ou limpando ?
        if -1 == self._ui.cbx_range.currentIndex(): return

        # bloqueia sinais para evitar que o clear() dispare funções prematuramente
        self._ui.cbx_date.blockSignals(True)
        self._ui.cbx_time.blockSignals(True)

        # limpa tudo que está abaixo na hierarquia
        self._ui.cbx_date.clear()
        self._ui.cbx_time.clear()

        # atualiza o próximo nível
        ut.update_datas(self._ui.cbx_station, self._ui.cbx_range, [self._ui.cbx_date],
                        self.pth_radar)

        # libera sinais
        self._ui.cbx_date.blockSignals(False)
        self._ui.cbx_time.blockSignals(False)

        # força a atualização do nível seguinte
        self.on_date_changed()

    # ---------------------------------------------------------------------------------
    def on_date_changed(self):
        """
        processa alteração na data
        """
        # logger
        M_LOG.debug(">> on_date_changed")

        # combo vazia ou limpando ?
        if -1 == self._ui.cbx_date.currentIndex(): return

        # bloqueia sinais para evitar que o clear() dispare funções prematuramente
        self._ui.cbx_time.blockSignals(True)

        # limpa tudo que está abaixo na hierarquia
        self._ui.cbx_time.clear()

        # atualiza o próximo nível
        ut.update_hora(self._ui.cbx_station, self._ui.cbx_range,
                       self._ui.cbx_date, self._ui.cbx_time,
                       self.pth_radar)

        # libera sinais
        self._ui.cbx_time.blockSignals(False)

    # ---------------------------------------------------------------------------------
    def on_estacao_changed(self):
        """
        gatilho acionado quando a estação muda
        """
        # logger
        M_LOG.debug(">> on_estacao_changed")

        # bloqueia sinais para evitar que o clear() dispare funções prematuramente
        self._ui.cbx_range.blockSignals(True)
        self._ui.cbx_date.blockSignals(True)
        self._ui.cbx_time.blockSignals(True)

        # limpa tudo que está abaixo na hierarquia
        self._ui.cbx_range.clear()
        self._ui.cbx_date.clear()
        self._ui.cbx_time.clear()

        # atualiza o próximo nível
        ut.update_alcances(self._ui.cbx_station, self._ui.cbx_range, self.pth_radar)

        # libera sinais
        self._ui.cbx_range.blockSignals(False)
        self._ui.cbx_date.blockSignals(False)
        self._ui.cbx_time.blockSignals(False)

        # força a atualização do nível seguinte
        self.on_alcance_changed()

    # ---------------------------------------------------------------------------------
    def on_field_changed(self):
        """
        gatilho acionado quando o campo muda
        """
        # logger
        M_LOG.debug(">> on_field_changed")

        # combo vazia ou limpando ? nenhum arquivo carregado ainda ?
        if -1 == self._ui.cbx_fields.currentIndex() or self.radar is None: return

        # field key selecionada
        ls_key = self._ui.cbx_fields.currentText()
        # field selecionado
        ls_field = self.radar.dct_fields[ls_key]

        # muda o field no radar
        self.radar.field_change(ls_field)

        # rebuild images
        self.rebuild_images()

    # ---------------------------------------------------------------------------------
    def on_mode_changed(self):
        """
        gatilho acionado quando o modo de exibição muda
        """
        # logger
        M_LOG.debug(">> on_mode_changed")

        # combo vazia ou limpando ? nenhum arquivo carregado ainda ?
        if -1 == self._ui.cbx_modes.currentIndex() or self.radar is None: return

        # bloqueia sinais para evitar que o clear() dispare funções prematuramente
        self._ui.cbx_modes.blockSignals(True)
        self._ui.cbx_val.blockSignals(True)

        # modo selecionado
        self.mode = self._ui.cbx_modes.currentText().split()[0]

        # limpa cbx_val
        self._ui.cbx_val.clear()

        # CAPPI ?
        if "CAPPI" == self.mode:
            # atualiza label
            self._ui.lbl_val.setText("Altitude:")
            # set range de valores
            self._ui.cbx_val.addItems([str(x) for x in range(1000, 16000, 1000)])

        # PPI ?
        elif "PPI" == self.mode:
            # atualiza label
            self._ui.lbl_val.setText("Ângulo de Elevação:")
            # set range de valores
            self._ui.cbx_val.addItems([str(x) for x in self.radar.elevation_list])

        # RHI Artificial ?
        elif "RHI-A" == self.mode:
            # atualiza label
            self._ui.lbl_val.setText("Azimute (Cardeal):")
            # set range de valores
            self._ui.cbx_val.addItems([str(x) for x in range(0, 360, 45)])

        # RHI real ?
        elif "RHI-R" == self.mode:
            # atualiza label
            self._ui.lbl_val.setText("Ângulo de Azimute:")
            # set range de valores
            self._ui.cbx_val.addItems([str(x) for x in range(0, 360, 10)])

        # senão,...
        else:
            # logger
            self.update_logger(f"modo {self.mode} inválido.")
            # quit fail
            return

        # rebuild all images for new mode
        self.rebuild_images()

        # libera sinais
        self._ui.cbx_modes.blockSignals(False)
        self._ui.cbx_val.blockSignals(False)

    # ---------------------------------------------------------------------------------
    def on_value_changed(self):
        """
        gatilho acionado quando o campo value muda
        """
        # logger
        M_LOG.debug(">> on_value_changed")

        # combo vazia ou limpando ?
        if -1 == self._ui.cbx_val.currentIndex(): return

        # index da key selecionada
        self.image_ndx = self._ui.cbx_val.currentIndex()

        # exibe a imagem
        self.show_image(self.image_ndx) 

    # ---------------------------------------------------------------------------------
    def on_velocity_changed(self):
        """
        gatilho acionado quando o campo velocity muda
        pode ir de 100 (rápido) a 2000 (lento) default é 250
        """
        # logger
        M_LOG.debug(">> on_velocity_changed")

        # player ativo ?
        if self.timer_ani.isActive():
            # configura velocidade do player
            self.timer_ani.start(self._ui.spn_vel.value())

    # ---------------------------------------------------------------------------------
    def open_file(self):
        """
        abre um diálogo para selecionar um arquivo de dados base avulso
        (menu Arquivo > Open file)
        """
        # logger
        M_LOG.debug(">> open_file")

        # diálogo de seleção (começa no diretório de dados)
        ls_file, _ = QtWidgets.QFileDialog.getOpenFileName(self,
                     "Selecione o arquivo de dados base",
                     str(self.pth_radar), "Volumes de radar (*.mvol);;Todos (*)")

        # usuário cancelou ?
        if not ls_file:
            # quit fail
            return

        self.display_1(MI_MSG_DADOS_SELECIONADOS)

        # carrega e exibe
        lpth_file = pathlib.Path(ls_file)
        self._load_radar_file(lpth_file.parent, lpth_file.name)

    # ---------------------------------------------------------------------------------
    def play_anima(self):
        """
        inicia a reprodução da lista de animação
        """
        # logger
        M_LOG.debug(">> play_anima")

        # clear to go
        if not self.playlist_atv:
            # quit fail
            return

        # se já estiver no fim,...
        if self.image_ndx >= len(self.playlist_atv):
            # volta ao início
            self.image_ndx = 0

            # ajusta comboxBox
            self._ui.cbx_val.setCurrentIndex(self.image_ndx)

        # define a velocidade (500ms = 2 quadros por segundo)
        self.timer_ani.start(self._ui.spn_vel.value())

    # ---------------------------------------------------------------------------------
    def plot_3d(self):
        """
        dispara a renderização 3D (botão "Gerar 3D")
        """
        # logger
        M_LOG.debug(">> plot_3d")

        # nenhum arquivo carregado ainda ?
        if self.radar is None:
            # logger
            self.update_logger("carregue um arquivo antes de gerar a visão 3D.")
            # quit fail
            return

        try:
            self.radar.render3D()

        # em caso de erro,...
        except Exception as l_err:
            # logger
            M_LOG.exception(f"[x] plot_3d: {l_err}")
            # feedback ao usuário
            self.update_logger(f"falha ao gerar visão 3D: {l_err}")

    # ---------------------------------------------------------------------------------
    def process_fields(self):
        """
        limpa, gera fields
        """
        # logger
        M_LOG.debug(">> process_fields")

        # bloqueia sinais para evitar que o clear() dispare funções prematuramente
        self._ui.cbx_fields.blockSignals(True)

        # clear fields
        self._ui.cbx_fields.clear()

        # itens de exibição disponíveis no arquivo
        for ls_fld in sorted(self.radar.dct_fields.keys()):
            # save on fields comboBoxes
            self._ui.cbx_fields.addItem(ls_fld)

        # long name
        ls_ln = self.radar.radar.fields[self.radar.field]["long_name"]

        # selecionar campo default do radar
        li_ndx = self._ui.cbx_fields.findText(ls_ln)

        if li_ndx >= 0:
            # seleciona a opção desejada
            self._ui.cbx_fields.setCurrentIndex(li_ndx)

        # libera sinais
        self._ui.cbx_fields.blockSignals(False)

    # ---------------------------------------------------------------------------------
    def rebuild_images(self):
        """
        rebuild all images
        """
        # logger
        M_LOG.debug(">> rebuild_images")

        # já existe um worker rodando (mode/campo trocados em sequência
        # rápida) ? ignora esta chamada em vez de disputar self.radar/
        # self.playlist_atv com o worker anterior
        if self.worker is not None and self.worker.isRunning():
            # logger
            M_LOG.debug("[!] rebuild_images: worker anterior ainda rodando, ignorando")
            # quit fail
            return

        # build config dict
        ldct_config = { "mode": self.mode,
                        "path": self.pth_images }

        # instancia a thread
        self.worker = iw.CRadarImageWorker(self.radar, ldct_config)

        # conecta os sinais aos métodos da interface
        self.worker.sgn_update_progress.connect(self.update_progressBar)
        self.worker.sgn_message_status.connect(self.update_statusBar)
        self.worker.sgn_list_finished.connect(self.finish_work)

        # desabilita o botão e os combos que mudam self.radar/self.mode
        # enquanto o worker roda em outra thread — sem isso, trocar campo/
        # modo durante o render dispara um novo on_field_changed/
        # on_mode_changed que muta self.radar concorrentemente com a
        # leitura feita pelo worker, sem nenhum lock
        self._ui.btn_load.setEnabled(False)
        self._ui.cbx_fields.setEnabled(False)
        self._ui.cbx_modes.setEnabled(False)
        self._ui.cbx_val.setEnabled(False)

        # inicia a execução em background
        self.worker.start()

    # ---------------------------------------------------------------------------------
    def set_path(self):
        """
        abre um diálogo para trocar o diretório-base de dados e repopula a
        lista de estações a partir dele (menu Arquivo > Open folder)
        """
        # logger
        M_LOG.debug(">> set_path")

        # diálogo de seleção (começa no diretório de dados atual)
        ls_dir = QtWidgets.QFileDialog.getExistingDirectory(self,
                 "Defina o diretório de dados base.", str(self.pth_radar))

        # usuário cancelou ?
        if not ls_dir:
            # quit fail
            return

        # novo diretório de dados (árvore <Estação>/<RRR>/*.mvol)
        self.pth_radar = pathlib.Path(ls_dir)
        self.display_1(MI_MSG_CAMINHO_TRABALHO_SELECIONADO)
        self.update_logger(str(self.pth_radar))

        # repopula estações -> alcances -> datas -> horários
        self._setup_stations()

    # ---------------------------------------------------------------------------------
    def show_image(self, fi_ndx):
        """
        show image from playlist

        :param fi_ndx: índice na playlist ativa (aceita -1 para a última imagem)
        """
        # logger
        M_LOG.debug(">> show_image")

        try:
            # carrega uma imagem de playlist
            l_img = QtGui.QPixmap(self.playlist_atv[fi_ndx])

            # coloca a imagem no label
            self._ui.lbl_image.setPixmap(l_img)

            # atualiza a statusBar
            ls_msg = f"image {fi_ndx + 1} de {len(self.playlist_atv)}"
            self.update_statusBar(ls_msg)

        # em caso de erro,...
        except Exception as l_err:
            # logger
            M_LOG.exception(f"[x] show_image: {l_err}")
            # feedback ao usuário
            self.update_statusBar(f"falha ao exibir imagem: {l_err}")

    # ---------------------------------------------------------------------------------
    def step_anima(self):
        """
        executa um step da animação
        """
        # logger
        M_LOG.debug(">> step_anima")

        # avança o index
        self.index_add()

        # show anime
        self.show_image(self.image_ndx)

    # ---------------------------------------------------------------------------------
    def stop_anima(self):
        """
        para a animação
        """
        # logger
        M_LOG.debug(">> stop_anima")

        # stop timer
        self.timer_ani.stop()

    # ---------------------------------------------------------------------------------
    def update_logger(self, fs_msg):
        """
        update logger
        """
        # logger
        M_LOG.debug(">> update_logger")

        # monta a menssagem
        ls_msg = f"{time.strftime('%H:%M:%S', time.localtime())}: {fs_msg}"

        # atualiza o registro de eventos
        self._ui.txb_events.append(ls_msg)

    # ---------------------------------------------------------------------------------
    def update_progressBar(self, fi_valor):
        """
        update progressBar
        """
        # logger
        M_LOG.debug(">> update_progressBar")

        # update progressBar
        self._ui.pgr_load.setValue(fi_valor)

    # ---------------------------------------------------------------------------------
    def update_statusBar(self, fs_msg):
        """
        update statusBar
        """
        # logger
        M_LOG.debug(">> update_statusBar")

        # update statusBar
        self.statusBar().showMessage(fs_msg)

# < the end >--------------------------------------------------------------------------
