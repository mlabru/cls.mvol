# -*- coding: utf-8 -*-
"""
Centro Logístico de Simulação Meteorológica
Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo

vv_radar

2026.out  mlabru  restaurado como modelo da GUI (removido de apps/radar/
                  como rd_radar.py, o que quebrou o volViewer): renomeado
                  para view/vv_radar.py, já que só a GUI o usa; o plot do
                  CAPPI (cp_cappi.cappi, hoje em .bkp/ do nowcast) foi
                  incorporado como _plot_cappi, com CI_CAPPI_VMIN/VMAX e
                  MT_FIGSIZE/MI_DPI; matplotlib forçado para o backend Agg
                  (com qtagg, cada figura criada na QThread era uma janela Qt)

2026.set  mlabru  preset cc.CFG_BLEND renomeado para cc.CFG_VIEWER
2026.set  mlabru  blend removido: CRadar passa a ser usado só pela GUI
                  (volViewer); comentários de cappi() atualizados
2026.set  mlabru  referencial de altitude do CAPPI: ff_alt_m é MSL e o grid
                  é montado em MSL (CFG_BLEND, altitude_ref="msl"), mas
                  cappi() (via cc.resolve_level) e
                  _alt_dentro_grid_cacheado comparavam ff_alt_m direto com o
                  eixo Z do grid, relativo ao radar -- o CAPPI saía ~altitude
                  do radar acima do pedido (ex: 3000 m -> ~3490 m MSL em CGU)
                  e 15000 m era tido como fora do grid, regenerando-o à toa;
                  agora ambos convertem ff_alt_m - self.altitude
2026.set  mlabru  - leitura (_load_radar) e gridding (generate_grid)
                    delegados a cappi.cp_core (read_radar/grid_radar, preset
                    CFG_BLEND), núcleo comum com cappi.py/nc_process_volume.py;
                    parâmetros e comentários de tuning movidos para o preset;
                    ls_gridding_algo/ls_roi_func removidas (eram calculadas
                    mas nunca repassadas a grid_from_radars)
2026.set  mlabru  renomeado de rv_radar.py; import de cp_cappi passa a
                  ser cappi.cp_cappi (movido para apps/cappi/)

2026.ago  mlabru  - cappi() não tratava mais a exceção de geração (re-raise,
                    propagando o erro real para o chamador em vez de um
                    frame ausente silencioso)
                  - cache de grid (self.grid_art) agora é invalidado quando
                    a altitude pedida sai do range do grid cacheado
                  - n_elevations_per_ray / start_of_reflectivity /
                    step_of_reflectivity / n_reflectivity_gates viram
                    escalares (eram arrays O(n_rays) só lidos em [0])
                  - start_of_speed / step_of_speed / n_speed_gates /
                    nyquist_velocity unificados para None quando não há dado
                    de velocidade
                  - self.x / self.y / self.z removidos (sem consumidor)
                  - extrai_data_radar() e set_mask() removidos (sem chamador) 
                  - lt_grid_shape extraído para constante MT_GRID_SHAPE
2026.jul  mlabru  - set_mask sobrescrevia campo original, bare except,
                    objeto parcialmente construído em FileNotFoundError,
                    extrai_data_radar frágil, generate_grid parâmetro
                    renomeado para semântica correta
2025.nov  mlabru  initial version (Linux/Python)
"""
# < imports >--------------------------------------------------------------------------

# python library
import dataclasses
import logging
import pathlib
import warnings
warnings.simplefilter("ignore")

# numPy
import numpy as np

# matplotlib -- backend Agg (sem GUI) antes do pyplot: os plots rodam na
# QThread do vv_image e, com o PyQt5 já importado, o default seria qtagg,
# que cria uma janela Qt por figura fora da thread da GUI (inseguro) e cujo
# plt.close() encerra o QApplication se nenhuma outra janela estiver visível
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# cartoPY
import cartopy.crs as crs

# Py-ART
import pyart

# cappi
import cappi.cp_core as cc

# < logging >--------------------------------------------------------------------------

# logger
M_LOG = logging.getLogger(__name__)
M_LOG.setLevel(logging.INFO)

# < constantes >-----------------------------------------------------------------------

# limites de refletividade (dBZ) usados em PPI/RHI/RHI artificial — diferem
# do range 0-70 usado para CAPPI (CI_CAPPI_VMIN/CI_CAPPI_VMAX) porque aqui o
# campo plotado é a refletividade bruta/não corrigida, que pode incluir
# retornos de baixa potência/ruído abaixo de 0 dBZ
#
# há outro par de limites/paleta de dBZ no nowcast (nwcCapGen.CF_DBZ_MIN/
# CF_DBZ_MAX) — ao ajustar um, cheque se o outro também precisa mudar
CI_PPI_VMIN = -32
CI_PPI_VMAX = 64

# limites de refletividade (dBZ) do colormap do CAPPI
CI_CAPPI_VMIN = 0
CI_CAPPI_VMAX = 70

# tamanho de figura (polegadas) e DPI de todos os plots: 7.01 x 5.11 pol.
# @ 100 DPI ≈ 701 x 511 pixels (vv_image.MI_IMG_WIDTH/MI_IMG_HEIGHT)
MT_FIGSIZE = (7.01, 5.11)
MI_DPI = 100

# shape da grade 3D usada em generate_grid (50 níveis verticais × 500×500)
# -- definida no preset cc.CFG_VIEWER (ver lá o porquê desses valores)
MT_GRID_SHAPE = (cc.CFG_VIEWER.n_levels,) + tuple(cc.CFG_VIEWER.shape_xy)

# < CRadar >---------------------------------------------------------------------------

class CRadar:
    """
    dados de radar volumétrico GAMIC-HDF5 (.mvol)

    lê o arquivo via Py-ART, expõe metadados, geometria e campos de dados,
    e oferece métodos de visualização (CAPPI, PPI, RHI, RHI artificial).

    metadata típica do GAMIC HDF5:
        {"Conventions": "CF/Radial instrument_parameters",
         "version": "1.3",
         "title": "",
         "institution": "",
         "references": "",
         "source": "",
         "history": "",
         "comment": "",
         "instrument_name": "",
         "original_container": "GAMIC-HDF5",
         "gamic_version": "8",
         "gamic_object": "PVOL",
         "gamic_date": "2025-12-21T17:56:45.000Z",
         "software": "FROG",
         "template_name": "400km_3elev_350hz",
         "site_name": "Cangucu",
         "host_name": "cgufrog",
         "azimuth_beam": np.float64(2.0),
         "elevation_beam": np.float64(2.0),
         "sdp_name": "UNKNOWN SDP",
         "sw_version": "generic-1000:frog-iacit:013012:174856",
         ...
         "simulated": "off"}
    """
    # ---------------------------------------------------------------------------------
    def __init__(self, fpth_path: pathlib.Path, fs_fname: str):
        """
        constructor

        :param fpth_path: diretório raiz onde o arquivo reside
        :param fs_fname: nome do arquivo (ex: "radar_20251221.mvol")

        :raises FileNotFoundError: se o arquivo não existir
        :raises RuntimeError: se o Py-ART não conseguir ler o arquivo

        objeto parcialmente construído eliminado (em caso de arquivo ausente
        raise FileNotFoundError em vez de retornar silenciosamente, evitando
        AttributeError posterior sem contexto claro).
        """
        # logger
        M_LOG.debug(">> constructor")

        # path absoluto
        self.pth_pathname = fpth_path / fs_fname

        # return silencioso substituído por exceção explícita.  O chamador
        # precisa saber que o objeto é inválido (um return precoce deixa
        # todos os atributos subsequentes indefinidos, causando
        # AttributeError opaco na próxima chamada de método).
        if not self.pth_pathname.exists():
            # monta mensagem
            ls_msg = f"arquivo não encontrado: {self.pth_pathname}"
            # logger
            M_LOG.error(f"[x] {ls_msg}")
            # raise an exception
            raise FileNotFoundError(ls_msg)

        # nome do arquivo sem extensão (usado em títulos de figuras)
        self.fname = self.pth_pathname.stem

        # lê o arquivo volumétrico (mvol) via Py-ART
        self._load_radar()

        # atributos de metadados
        self.metadata = self.radar.metadata

        # número de raios
        self.n_rays   = self.radar.nrays
        # número de elevações únicas
        self.n_sweeps = self.radar.nsweeps

        # número de elevações disponíveis (igual para todos os raios no
        # GAMIC PVOL. É o número de sweeps (elevações únicas) da
        # varredura). Escalar — antes era np.full(self.n_rays, ...), um
        # array O(n_rays) alocado à toa já que só era lido em [0]
        self.n_elevations_per_ray = self.n_sweeps

        # localização do radar
        self.latitude  = self.radar.latitude["data"][0]
        self.longitude = self.radar.longitude["data"][0]
        self.altitude  = self.radar.altitude["data"][0]
        # último gate = alcance máximo em metros
        self.range = self.radar.range["data"][-1]

        # logger 
        M_LOG.info(f"[+] Radar @ {self.latitude:.2f}, {self.longitude:.2f}, "
                   f"altitude {self.altitude:.1f} m "
                   f"| alcance {self.range/1000:.0f} km")

        # geometria e varredura
        self.elevation      = self.radar.elevation["data"]      # real por raio
        self.azimuth        = self.radar.azimuth["data"]        # real por raio
        self.elevation_list = self.radar.fixed_angle["data"]    # ângulos nominais

        # distâncias radiais (em metros).  Escalares — antes eram
        # np.full(self.n_rays, ...), arrays O(n_rays) alocados à toa já que
        # os únicos consumidores (vv_view.py) só liam o índice [0]
        self.start_of_reflectivity  = self.radar.range["data"][0]
        self.step_of_reflectivity   = self.radar.range["meters_between_gates"]
        # número de gates de refletividade por raio
        self.n_reflectivity_gates   = self.radar.ngates

        # velocidade (se disponível no arquivo).  Sem consumidor atual em
        # apps/ ou test/ — mantido como preparação para funcionalidade
        # futura; usa None como sentinela única (antes o branch "sem
        # velocidade" usava ["N/A"], tipo incompatível com o ndarray do
        # branch "com velocidade")
        if "velocity" in self.radar.fields:
            # no mvol, gates de velocidade coincidem com os de refletividade
            self.start_of_speed = self.start_of_reflectivity
            self.step_of_speed  = self.step_of_reflectivity
            self.n_speed_gates  = self.n_reflectivity_gates

            # velocidade de Nyquist como limite de velocidade mensurável
            self.nyquist_velocity = self.radar.instrument_parameters.get(
                "nyquist_velocity", {"data": np.array([0.])}
            )["data"]

        else:
            self.start_of_speed   = None
            self.step_of_speed    = None
            self.n_speed_gates    = None
            self.nyquist_velocity = None

        # nome da estratégia (VCP - Volume Coverage Pattern)
        self.vcp = self.radar.metadata.get("vcp_value", "Unknown")

        if "Unknown" == self.vcp:
            # em alguns arquivos GAMIC, o nome da tarefa (task) define o VCP.
            # 'instrument_parameters' é atributo de topo do objeto Py-ART
            # (não uma chave dentro de radar.metadata); acesso defensivo pois
            # o layout exato varia entre arquivos GAMIC
            try:
                # busca o nome da tarefa
                self.vcp = self.radar.instrument_parameters.get(
                    "task_name", {}
                ).get("data", ["Default"])[0]

            # em caso de erro,...
            except (AttributeError, KeyError, IndexError, TypeError):
                # sem informação de tarefa disponível
                self.vcp = "Default"

        # tipo de varredura: geralmente "ppi" ou "rhi"
        self.scan_type = self.radar.scan_type

        # mapeamento long_name → chave interna do campo (ex: "Reflectivity" → "DBZ")
        self.dct_fields = { lv["long_name"]: lk
                            for lk, lv in self.radar.fields.items() }

        # campo de trabalho atual
        self.field = None
        # OBS: field_change verifica (self.field == fs_new_field) logo na entrada;
        # self.field=None garante que a comparação nunca será True prematuramente,
        # mas a inicialização depende dessa ordem !! não inverter !!.
        self.field_change("corrected_reflectivity")

        # grade 3D (gerada sob demanda em generate_grid)
        self.grid_dbz = None   # array numpy com dados brutos da grade
        self.grid_art = None   # objeto pyart.core.Grid

    # ---------------------------------------------------------------------------------
    def cappi(self, ff_alt_m: float = 3000., fs_save_path: str = None):
        """
        gera imagem CAPPI (Constant Altitude Plan Position Indicator) para
        uma altitude específica utilizando GridMapDisplay do Py-ART.

        :param ff_alt_m: altitude de interesse em metros MSL (default: 3000 m)
        :param fs_save_path: caminho de saída do arquivo de imagem (opcional)

        :raises Exception: propaga qualquer falha de geração/gridding/plot —
                           o chamador (a GUI, vv_image) já trata isso
        """
        # logger
        M_LOG.debug(">> cappi")

        # (re)gera o grid 3D se ainda não existir OU se a altitude pedida
        # cair fora do range de altitude já coberto pelo grid cacheado — sem
        # essa checagem, uma chamada com altitude fora do range de um grid
        # cacheado por uma chamada anterior reaproveitaria o grid errado, e
        # cc.resolve_level clamparia silenciosamente o nível pedido
        # para a borda mais próxima disponível
        if self.grid_art is None or not self._alt_dentro_grid_cacheado(ff_alt_m):
            # gera o grid 3D cobrindo pelo menos a altitude pedida (o grid
            # nunca sobe acima de 3000 m de altitude mínima, senão o nível
            # mais baixo do CAPPI ficaria fora do range do grid e seria
            # silenciosamente clampado por cc.resolve_level)
            self.grid_art = self.generate_grid(ff_alt_min_m=min(ff_alt_m, 3000.))

        # gera imagem CAPPI.  Não engole mais a exceção aqui: uma falha na
        # geração precisa chegar ao chamador (a GUI, que já está preparada
        # com seu próprio try/except) em vez de virar uma imagem ausente
        # silenciosa
        self._plot_cappi(ff_alt_m, fs_save_path)

    # ---------------------------------------------------------------------------------
    def _plot_cappi(self, ff_alt_m: float, fs_save_path: str = None):
        """
        plota o CAPPI do grid cacheado (self.grid_art) usando o display
        nativo do Py-ART (GridMapDisplay) -- antigo cp_cappi.cappi

        :param ff_alt_m: altitude em metros MSL
        :param fs_save_path: caminho de saída do arquivo de imagem (opcional)

        :raises ValueError: se o campo ativo não estiver no grid
        """
        # logger
        M_LOG.debug(">> _plot_cappi")

        # valida o campo no grid antes de tentar plotar, evitando KeyError
        # tardio dentro do Py-ART sem contexto claro
        if self.field not in self.grid_art.fields:
            # raise an exception
            raise ValueError(f"cappi: campo '{self.field}' não encontrado no grid. "
                             f"Campos disponíveis: {list(self.grid_art.fields.keys())}")

        # índice de nível: o eixo Z do grid é relativo ao radar (origem do
        # grid), então a altitude MSL pedida é convertida para esse
        # referencial -- comparar MSL direto com Z escolhia um nível
        # ~altitude do radar acima do pedido
        li_level = cc.resolve_level(self.grid_art, ff_alt_m - self.altitude)

        # eixo Z convertido para MSL (rastreabilidade)
        lnp_z = self.grid_art.z["data"] + self.altitude

        # logger
        M_LOG.info(f"[+] CAPPI: altitude solicitada={ff_alt_m:.0f} m  "
                   f"→  nível={li_level}  altitude real={lnp_z[li_level]:.0f} m")

        # define o tamanho da figura em polegadas para aproximar de 701x511 pixels
        l_fig = plt.figure(figsize=MT_FIGSIZE, dpi=MI_DPI)

        # define os plots e projeção da figura
        l_ax = l_fig.add_subplot(111, projection=crs.PlateCarree())

        # monta um objeto "display" do Py-ART
        l_display = pyart.graph.GridMapDisplay(self.grid_art)

        # plota o cappi
        l_display.plot_grid(self.field,
                            level=li_level,
                            vmin=CI_CAPPI_VMIN,
                            vmax=CI_CAPPI_VMAX,
                            ax=l_ax,
                            cmap="NWSRef",
                            colorbar_label="Refletividade (dBZ)")

        # título da figura
        plt.title(f"CAPPI {ff_alt_m:.0f} m - {self.radar.metadata['gamic_date']}",
                  fontsize=10)

        # nome dos eixos x e y
        l_ax.set_xlabel("Longitude (°)", fontsize=15)
        l_ax.set_ylabel("Latitude (°)", fontsize=15)

        if fs_save_path:
            # salva a figura
            plt.savefig(fs_save_path, bbox_inches="tight", pad_inches=0.1)

        # fecha a figura para não estourar a memória RAM (mesmo sem salvar)
        plt.close(l_fig)

    # ---------------------------------------------------------------------------------
    def _alt_dentro_grid_cacheado(self, ff_alt_m: float) -> bool:
        """
        indica se a altitude pedida está dentro do range de altitude coberto
        pelo grid 3D já cacheado em self.grid_art.

        :param ff_alt_m: altitude pedida em metros MSL

        :returns: True se dentro do range do grid cacheado
        """
        # logger
        M_LOG.debug(">> _alt_dentro_grid_cacheado")

        # coordenadas Z reais do grid cacheado (relativas ao radar -- origem
        # do grid)
        lnp_z = self.grid_art.z["data"]

        # altitude pedida (MSL) no referencial do grid
        lf_alt_grid = ff_alt_m - self.altitude

        # dentro do range coberto?
        return lnp_z.min() <= lf_alt_grid <= lnp_z.max()

    # ---------------------------------------------------------------------------------
    def field_change(self, fs_new_field: str) -> None:
        """
        define o campo de trabalho ativo.

        se fs_new_field não existir no radar, usa o primeiro campo disponível
        como fallback com aviso de log.

        :param fs_new_field: nome do campo desejado (ex: "corrected_reflectivity")
        """
        # logger
        M_LOG.debug(">> field_change")

        # sem mudança (evita reset desnecessário do grid)
        if self.field == fs_new_field:
            # ok
            return

        # define o campo solicitado
        self.field = fs_new_field

        # campo inválido → fallback para o primeiro disponível
        if self.field not in self.radar.fields:
            # primeiro item da lista de campos disponíveis
            ls_fallback = list(self.radar.fields.keys())[0]
            # logger
            M_LOG.warning(f"[!] campo '{fs_new_field}' não encontrado; "
                          f"usando fallback '{ls_fallback}'")
            # define o compo
            self.field = ls_fallback

        # invalida o cache do grid (será regenerado na próxima chamada de cappi())
        self.grid_dbz = None
        self.grid_art = None

    # ---------------------------------------------------------------------------------
    def generate_grid(self, ff_alt_min_m: float = 3000.):
        """
        gera grade 3D (pyart.core.Grid) a partir do volume polar do radar.

        :param ff_alt_min_m: altitude mínima do grid em metros (default: 3000 m)

        :returns: pyart.core.Grid com o campo ativo interpolado
        """
        # logger
        M_LOG.debug(">> generate_grid")
        # logger
        M_LOG.info(f"[+] gerando grid 3D: {self.radar.metadata['gamic_date']}  "
                   f"alt_min={ff_alt_min_m:.0f} m ...")

        # preset do CRadar (50 níveis de ff_alt_min_m a 15000 m MSL, ±último
        # gate, origem no radar, Barnes2, min_radius 1750 m -- ver cc.CFG_VIEWER)
        # com a altitude mínima pedida e o campo de trabalho atual
        l_cfg = dataclasses.replace(cc.CFG_VIEWER, z_min_m=ff_alt_min_m,
                                    field_name=self.field)

        # gera grade 3D
        return cc.grid_radar(self.radar, l_cfg)

    # ---------------------------------------------------------------------------------
    def _load_radar(self):
        """
        carrega o arquivo de radar via Py-ART.

        tenta primeiro o leitor nativo GAMIC (read_gamic); se falhar, usa o
        leitor genérico (read) que detecta o formato automaticamente.

        :raises RuntimeError: se nenhum dos leitores conseguir abrir o arquivo
        """
        # logger
        M_LOG.debug(">> _load_radar")

        # read_gamic com fallback para pyart.io.read (ver cc.read_radar)
        self.radar = cc.read_radar(self.pth_pathname, "pyart")

    # ---------------------------------------------------------------------------------
    def ppi(self, fi_sweep: int = 0, fs_save_path: str = None):
        """
        visualização PPI (Plan Position Indicator) do sweep indicado.

        :param fi_sweep: índice do sweep (default: 0 — menor elevação)
        :param fs_save_path: caminho de saída (opcional)
        """
        # logger
        M_LOG.debug(">> ppi")

        # cria display Py-ART
        l_display = pyart.graph.RadarDisplay(self.radar)

        # ângulo de elevação nominal do sweep
        lf_angle = self.elevation_list[fi_sweep]

        # define o tamanho da figura em polegadas para aproximar de 701x511 pixels
        l_fig = plt.figure(figsize=MT_FIGSIZE, dpi=MI_DPI)
        l_ax  = l_fig.add_subplot(111)

        # plota PPI com colormap NWSRef
        l_display.plot_ppi(self.field, fi_sweep,
                           vmin=CI_PPI_VMIN, vmax=CI_PPI_VMAX, ax=l_ax, cmap="NWSRef",
                           title=f"PPI {self.fname} - Elev: {lf_angle:.1f}°")

        ## l_display.plot_range_rings([50, 100])

        if fs_save_path:
            # save figure
            plt.savefig(fs_save_path, bbox_inches="tight", pad_inches=0.1)

        # fecha a figura para não estourar a memória RAM (mesmo sem salvar)
        plt.close(l_fig)

    # ---------------------------------------------------------------------------------
    def render3D(self):
        """
        renderização 3D volumétrica (stub — módulo rv_render comentado).
        """
        # logger
        M_LOG.debug(">> render3D")

        # renderização VTK (rv_render) desativada — evita o custo de gerar
        # um grid 3D (50x500x500) para um método que hoje não renderiza nada
        M_LOG.warning("[!] render3D desativado (rv_render não integrado)")
        return

    # ---------------------------------------------------------------------------------
    def rhi(self, fi_sweep: int = 0, fs_save_path: str = None):
        """
        gera um corte vertical RHI (Range Height Indicator) de um sweep específico.

        :param fi_sweep: índice do sweep (clampado ao número de sweeps disponíveis)
        :param fs_save_path: caminho de saída (opcional)
        """
        # logger
        M_LOG.debug(">> rhi")

        # clamp circular — evita IndexError se fi_sweep > nsweeps
        fi_sweep = fi_sweep % len(self.radar.fixed_angle["data"])

        # create figure
        l_fig = plt.figure(figsize=MT_FIGSIZE, dpi=MI_DPI)
        l_ax  = l_fig.add_subplot(111)

        # create radar display
        l_display = pyart.graph.RadarDisplay(self.radar)

        # no RHI o "fixed_angle" representa o azimute
        lf_azi = self.radar.fixed_angle["data"][fi_sweep]

        # plota RHI
        l_display.plot_rhi(self.field, fi_sweep,
                           vmin=CI_PPI_VMIN, vmax=CI_PPI_VMAX, ax=l_ax, cmap="NWSRef",
                           title=f"RHI {self.fname} - Azimute: {lf_azi:.1f}°")

        # limites: 0–15 km de altura; 0–alcance km de distância
        l_ax.set_ylim(0, 15)
        l_ax.set_xlim(0, self.range / 1000)

        if fs_save_path:
            # salva figura
            plt.savefig(fs_save_path, bbox_inches="tight", pad_inches=0.1)

        # fecha a figura para não estourar a memória RAM (mesmo sem salvar)
        plt.close(l_fig)

    # ---------------------------------------------------------------------------------
    def rhi_artificial(self, ff_azim: float = 0., fs_save_path: str = None):
        """
        gera um RHI artificial (cross-section extraído de dados PPI) para o
        azimute solicitado.

        :param ff_azim: azimute desejado em graus (default: 0°)
        :param fs_save_path: caminho de saída (opcional)
        """
        # logger
        M_LOG.debug(">> rhi_artificial")

        # create figure
        l_fig = plt.figure(figsize=MT_FIGSIZE, dpi=MI_DPI)
        l_ax  = l_fig.add_subplot(111)

        # extrai corte vertical do volume PPI no azimute solicitado
        # cross_section_ppi espera lista ou array
        xsect = pyart.util.cross_section_ppi(self.radar, [ff_azim])

        # create radar display
        l_display = pyart.graph.RadarDisplay(xsect)

        # plota sweep 0 do cross-section (único sweep extraído)
        l_display.plot_rhi(self.field, 0,
                           vmin=CI_PPI_VMIN, vmax=CI_PPI_VMAX, ax=l_ax, cmap="NWSRef",
                           title=f"RHI Artificial - Azimute: {ff_azim:.1f}°")

        # ajuste de escala vertical: 0 a 15 km
        l_ax.set_ylim(0, 15)

        if fs_save_path:
            # salva a figura
            plt.savefig(fs_save_path, bbox_inches="tight", pad_inches=0.1)

        # fecha a figura para não estourar a memória RAM (mesmo sem salvar)
        plt.close(l_fig)

# < the end >--------------------------------------------------------------------------
