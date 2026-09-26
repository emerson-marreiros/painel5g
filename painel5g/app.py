"""
app.py — Otimização de Alocação de Espectro 5G (Streamlit).

Um único cenário (torres P1…Pn com posição e potência) alimenta todos os gráficos:
  1 Pontos → 2 Voronoi → 3 Power-Voronoi → 4 Sinal real → 5 Rede e canais → 6 SINR.
Cada gráfico tem seus controles logo abaixo (na horizontal) e uma legenda com o que
cada variável representa. Os controles são lidos primeiro e os gráficos desenhados
depois, em espaços reservados acima deles — por isso até a ficha ⓘ do gráfico 1 já
mostra o canal alocado no gráfico 5.
"""

import numpy as np
import pandas as pd
import streamlit as st

import explorer_geometry as geo
import explorer_ui as ui
from explorer_ui import ALLOC_METHODS, BANDS, MAX_POINTS, WEIGHT_MODELS, label

st.set_page_config(page_title="Otimização de Alocação de Espectro 5G", layout="wide")

st.title("📡 Otimização de Alocação de Espectro 5G")
st.markdown(
    "Painel interativo que parte de um conjunto de torres (gNodeBs), analisa a geometria das células "
    "(Voronoi e Power-Voronoi), a cobertura real do sinal, a alocação de canais entre células vizinhas e o "
    "desempenho de rádio percebido pelos usuários.  \n"
    "**Todos os gráficos usam as mesmas torres:** ao mudar a quantidade de pontos, a área ou editar uma torre na "
    "tabela, tudo é recalculado. Os controles **abaixo de cada gráfico** são as variáveis livres daquele gráfico.")


def section(title: str, intro: str, ratio=(3, 2)):
    """Reserva os espaços de uma seção: gráfico | painel lateral, controles (horizontal) e legenda."""
    st.divider()
    st.subheader(title)
    st.caption(intro)
    chart, side = st.columns(ratio)
    controls = st.container(border=True)
    legend = st.container()
    return chart.container(), side.container(), controls, legend


def write_legend(slot, reading: str, variables: str) -> None:
    with slot.expander("📖 Legenda — o que o gráfico mostra e o que cada variável faz", expanded=True):
        a, b = st.columns(2)
        a.markdown("**Como ler o gráfico**\n\n" + reading)
        b.markdown("**Variáveis deste gráfico**\n\n" + variables)


# =============================================================================
# 1 · CONTROLES (lidos antes de desenhar)
# =============================================================================
ctrl: dict = {}

# --- 1 · Pontos ---------------------------------------------------------------
s1 = section("1 · Torres (pontos)", "Define o cenário usado por todos os gráficos abaixo.")
with s1[2]:
    c = st.columns(6)
    ctrl["n"] = c[0].slider("Quantidade de pontos", 0, MAX_POINTS, 6,
                            help="Número de torres (gNodeBs). Vale para todos os gráficos.")
    ctrl["L"] = c[1].slider("Área (m)", 300.0, 2000.0, 800.0, step=100.0,
                            help="Lado do terreno quadrado simulado.")
    ctrl["seed"] = int(c[2].number_input("Semente dos pontos", value=7, step=1,
                                         help="Mesma semente = mesmas posições (reprodutível)."))
    ctrl["weight_source"] = c[3].radio("Potência inicial", ["Aleatória", "Manual"], horizontal=True,
                                       help="Aleatória: 30–46 dBm sorteados. Manual: todas em 40 dBm.")
    ctrl["power_seed"] = int(c[4].number_input("Semente das potências", value=1, step=1,
                                               disabled=ctrl["weight_source"] == "Manual"))
    if ctrl["weight_source"] == "Manual":
        ctrl["power_seed"] = 0
    p1_circles = c[5].checkbox("Mostrar raios", value=True, key="p1_circ")
    p1_sized = c[5].checkbox("Tamanho = potência", value=True, key="p1_size")
write_legend(
    s1[3],
    "- **Cada ponto colorido** é uma torre (P1…Pn); a cor identifica a torre em todos os gráficos.\n"
    "- **Tamanho do ponto** proporcional à potência Tx.\n"
    "- **Círculo tracejado** = raio de cobertura (onde o RSRP chega ao mínimo definido no gráfico 3).\n"
    "- **Círculo azul “i”** = ficha da torre: posição, potência, raio, vizinhos, áreas e canal alocado.\n"
    "- **Tabela ao lado**: edite X, Y ou potência de qualquer torre — todos os gráficos acompanham.",
    "- **Quantidade de pontos**: nº de torres (0–10) do cenário inteiro.\n"
    "- **Área**: tamanho do terreno; influencia distâncias, cobertura e atenuação.\n"
    "- **Semente dos pontos / das potências**: fixam o sorteio para repetir o mesmo cenário.\n"
    "- **Potência inicial**: sorteada (mistura de small cells, micro e macro) ou igual para todas.\n"
    "- **Mostrar raios / Tamanho = potência**: opções só de visualização deste gráfico.")

if ctrl["n"] == 0:
    with s1[1]:
        st.info("Nenhum ponto selecionado. Aumente **Quantidade de pontos** (máx. 10) para ver os gráficos.")
    st.stop()

# --- 2 · Voronoi ----------------------------------------------------------------
s2 = section("2 · Voronoi clássico e distâncias",
             "Divide a área pela torre geometricamente mais próxima — sem considerar potência.")
with s2[2]:
    c = st.columns(5)
    v_fill = c[0].toggle("Preencher células", value=True)
    v_links = c[1].toggle("Ligações entre vizinhos", value=True)
    v_dist = c[2].toggle("Rótulos de distância", value=True)
    h_which = c[3].radio("Histograma", ["Ambos", "Todos os pares", "Só vizinhos"], horizontal=True)
    h_bins = c[4].slider("Faixas do histograma", 3, 20, 8, key="dist_bins")
write_legend(
    s2[3],
    "- **Regiões coloridas** = célula de cada torre: pontos mais próximos dela do que de qualquer outra.\n"
    "- **Linha branca** = fronteira (mediatriz): fica exatamente no meio entre duas torres.\n"
    "- **Linha pontilhada + rótulo** = distância entre torres vizinhas (que dividem fronteira).\n"
    "- **Histograma**: como as distâncias se distribuem; linhas vermelha (média) e verde (mediana).\n"
    "- **Métricas**: *geral* usa todos os pares; *entre vizinhos* só quem disputa usuários.",
    "- **Preencher células / Ligações / Rótulos**: ligam e desligam camadas do diagrama.\n"
    "- **Histograma**: escolhe quais distâncias comparar (todos os pares × só vizinhos).\n"
    "- **Faixas do histograma**: resolução das barras (mais faixas = mais detalhe).\n"
    "- As **torres** vêm do gráfico 1 — este gráfico não depende de potência.")

# --- 3 · Power-Voronoi ------------------------------------------------------------
s3 = section("3 · Power-Voronoi 5G (peso = intensidade da torre)",
             "Cada torre ganha um peso pela sua potência; torres fortes empurram a fronteira para longe.")
with s3[2]:
    c = st.columns(6)
    band = c[0].selectbox("Faixa de frequência", list(BANDS), index=1,
                          help="Frequência mais alta = mais perda = menor alcance.")
    ctrl["band"] = band
    ctrl["freq"], ctrl["n_rb"], band_bw = BANDS[band]
    ctrl["gain"] = c[1].slider("Ganho da antena (dBi)", 0.0, 25.0, 15.0, step=0.5,
                               help="Setorial macro ≈ 15–18 dBi · mmWave com beamforming ≈ 25 dBi.")
    ctrl["n_exp"] = c[2].slider("Expoente de perda (n)", 2.0, 4.5, 3.5, step=0.1,
                                help="2 = espaço livre · 2,7–3,5 = urbano · 4+ = urbano denso/indoor.")
    ctrl["threshold"] = c[3].slider("RSRP mínimo (dBm)", -130.0, -80.0, -110.0, step=1.0,
                                    help="Abaixo disso o terminal fica sem cobertura (≈ −110 dBm é borda típica).")
    ctrl["weight_model"] = WEIGHT_MODELS[c[4].radio("Modelo de peso", list(WEIGHT_MODELS))]
    p3_circles = c[5].checkbox("Raios de cobertura", value=True, key="p3_circ")
    p3_marks = c[5].checkbox("Marcas ✕ nas fronteiras", value=True)
    p3_opacity = c[5].slider("Opacidade", 0.2, 1.0, 0.55, step=0.05)
write_legend(
    s3[3],
    "- **Cores** = área atendida por cada torre no Power-Voronoi; **cinza** = sem cobertura.\n"
    "- **Linha branca** = fronteira (eixo radical): reta, mas deslocada para o lado da torre mais fraca.\n"
    "- **✕** = onde a fronteira corta a linha entre duas torres (passe o mouse para ver as distâncias).\n"
    "- **Círculo tracejado** = raio de cobertura de cada torre.\n"
    "- **Métricas**: quanto cada diagrama acerta a torre de melhor sinal real (gráfico 4).",
    "- **Faixa de frequência**: 700 MHz alcança longe; 26 GHz perde muito sinal com a distância.\n"
    "- **Ganho da antena**: soma à potência irradiada (EIRP) e aumenta o alcance.\n"
    "- **Expoente de perda n**: quão rápido o sinal cai com a distância (ambiente).\n"
    "- **RSRP mínimo**: nível de sinal abaixo do qual o usuário fica sem serviço.\n"
    "- **Modelo de peso**: como a potência vira peso w — *calibrado* segue o sinal real; *r²* exagera torres "
    "fortes.\n"
    "- Estes parâmetros de propagação também valem para os gráficos 4, 5 e 6.")

# --- 4 · Sinal real ----------------------------------------------------------------
s4 = section("4 · Sinal real (melhor servidor)",
             "Mapa calculado ponto a ponto: cada lugar é servido pela torre de maior RSRP.")
with s4[2]:
    c = st.columns(4)
    r_step = c[0].slider("Passo das curvas de RSRP (dB)", 2, 20, 10)
    ctrl["grid_res"] = c[1].slider("Resolução do mapa (px)", 80, 300, 220, step=20,
                                   help="Mais pixels = mapa mais fino e métricas mais precisas (e mais lento).")
    r_contours = c[2].toggle("Curvas de RSRP", value=True)
    r_borders = c[3].toggle("Fronteiras Power-Voronoi", value=True)
write_legend(
    s4[3],
    "- **Cores** = torre com o **maior sinal** em cada ponto do terreno (a “verdade” do modelo).\n"
    "- **Linhas finas** = curvas de mesmo RSRP (dBm), como curvas de nível do sinal.\n"
    "- **Linha vermelha** = limite de cobertura (RSRP mínimo do gráfico 3); fora dela, cinza.\n"
    "- **Tracejado branco** = fronteiras do Power-Voronoi, para comparar com as cores reais.\n"
    "- A fronteira real é um arco de círculo; o Power-Voronoi é a aproximação reta dela.",
    "- **Passo das curvas**: distância em dB entre duas curvas de RSRP.\n"
    "- **Resolução do mapa**: nº de pixels por lado da grade (afeta também as áreas do gráfico 3).\n"
    "- **Curvas de RSRP / Fronteiras Power-Voronoi**: ligam e desligam as camadas.\n"
    "- Torres vêm do gráfico 1; faixa, ganho, n e RSRP mínimo vêm do gráfico 3.")

# --- 5 · Rede e canais ---------------------------------------------------------------
s5 = section("5 · Rede: usuários e alocação de canais",
             "Usuários conectam na torre de melhor sinal; vizinhos no mesmo canal interferem entre si.")
with s5[2]:
    c = st.columns(7)
    ctrl["n_users"] = c[0].slider("Usuários", 20, 300, 100, step=10)
    ctrl["hotspot"] = c[1].slider("Hotspot (%)", 0, 100, 60, step=5) / 100
    ctrl["hotspot_tower"] = c[2].selectbox("Centro do hotspot", range(ctrl["n"]), format_func=label,
                                           help="Torre perto da qual os usuários do hotspot se concentram.")
    ctrl["ue_seed"] = int(c[3].number_input("Semente dos usuários", value=42, step=1))
    ctrl["n_channels"] = c[4].slider("Canais (F)", 1, 4, 3,
                                     help="Frequências disponíveis para distribuir entre as torres.")
    ctrl["alloc_method"] = ALLOC_METHODS[c[5].radio("Estratégia de alocação", list(ALLOC_METHODS))]
    n_graph = c[6].checkbox("Grafo de interferência", value=True)
    n_ues = c[6].checkbox("Mostrar usuários", value=True)
write_legend(
    s5[3],
    "- **Cor da célula e da torre** = canal (frequência) alocado a ela.\n"
    "- **Pontos magenta** = usuários (UEs); passe o mouse para ver a torre servidora e o SINR.\n"
    "- **Linhas entre torres** = grafo de interferência (vizinhos no Power-Voronoi); espessura = peso "
    "(carga das duas células ÷ distância).\n"
    "- **Linha vermelha** = vizinhos no **mesmo canal** → interferência co-canal.\n"
    "- **Tabela**: canal, carga e conflitos de cada torre.",
    "- **Usuários**: total de dispositivos demandando tráfego.\n"
    "- **Hotspot (%)**: fração dos usuários concentrada perto da torre escolhida em *Centro do hotspot*.\n"
    "- **Semente dos usuários**: fixa o sorteio dos usuários.\n"
    "- **Canais (F)**: quantas frequências podem ser reutilizadas; com 1 canal todos interferem.\n"
    "- **Estratégia**: *Minimizar interferência* (gulosa + refinamento) evita dar o mesmo canal a vizinhos "
    "carregados; *Aleatória* e *Canal único* servem de comparação.")

# --- 6 · SINR -------------------------------------------------------------------------
s6 = section("6 · Desempenho de rádio (SINR)",
             "Qualidade do sinal de cada usuário considerando a interferência dos vizinhos no mesmo canal.")
with s6[2]:
    c = st.columns(4)
    ctrl["bw"] = c[0].slider("Banda (MHz)", 5.0, 100.0, band_bw, step=5.0, key=f"bw_{band}",
                             help="Começa na largura de banda da faixa escolhida no gráfico 3.")
    ctrl["nf"] = c[1].slider("Figura de ruído (dB)", 0.0, 15.0, 7.0, step=0.5,
                             help="Ruído extra do receptor do celular (tipicamente 7–9 dB).")
    ctrl["outage_db"] = c[2].slider("Limiar de outage (dB)", -10.0, 10.0, 0.0, step=0.5)
    s_bins = c[3].slider("Faixas do histograma", 10, 60, 30, key="sinr_bins")
write_legend(
    s6[3],
    "- **Barras** = quantos usuários têm cada valor de SINR; **curva** = densidade suavizada (KDE).\n"
    "- **Linha vermelha tracejada** = limiar de outage: à esquerda dela o usuário não consegue se conectar bem.\n"
    "- **SINR** = sinal ÷ (interferência co-canal + ruído), em dB.\n"
    "- **Throughput** = capacidade de Shannon B·log₂(1+SINR). **Jain** = equidade (1 = todos iguais).",
    "- **Banda (MHz)**: largura do canal — mais banda = mais throughput, mas também mais ruído.\n"
    "- **Figura de ruído**: piora o piso de ruído N = −174 dBm/Hz + 10·log₁₀(B) + NF.\n"
    "- **Limiar de outage**: SINR mínimo aceitável para contar o usuário como atendido.\n"
    "- **Faixas do histograma**: resolução das barras.\n"
    "- Potências vêm da tabela (gráfico 1), propagação do gráfico 3 e canais do gráfico 5.")


# =============================================================================
# 2 · CÁLCULO — um único resultado compartilhado por todos os gráficos
# =============================================================================
with s1[1]:
    pts, ptx = ui.points_editor(ctrl)
ui.notify_changes(pts, ptx, ctrl)
r = ui.compute(pts, ptx, ctrl)
n, stats, ev = r["n"], r["stats"], r["ev"]
names = [label(i) for i in range(n)]


def chart(slot, fig, key):
    with slot:
        st.plotly_chart(fig, key=key, theme=None)


# =============================================================================
# 3 · DESENHO
# =============================================================================
# 1 · Pontos
chart(s1[0], ui.fig_points(r, show_circles=p1_circles, size_by_power=p1_sized), "fig_points")

# 2 · Voronoi
chart(s2[0], ui.fig_voronoi(r, show_links=v_links, show_dist=v_dist, fill=v_fill), "fig_voronoi")
with s2[1]:
    if n < 2:
        st.info("Com 1 ponto não há distâncias: a célula ocupa a área inteira.")
    else:
        m = st.columns(2)
        m[0].metric("Distância média geral", f"{stats['mean_all']:.1f} m", help="Média de todos os pares Pi–Pj.")
        m[1].metric("Mediana geral", f"{stats['median_all']:.1f} m")
        m[0].metric("Média entre vizinhos", f"{stats['mean_neighbors']:.1f} m",
                    help="Só pares que dividem fronteira no Voronoi (quem de fato disputa usuários).")
        m[1].metric("Mediana entre vizinhos", f"{stats['median_neighbors']:.1f} m")
        m[0].metric("Vizinho mais próximo (média)", f"{stats['mean_nearest']:.1f} m")
        m[1].metric("Mín · Máx", f"{stats['min_all']:.0f} · {stats['max_all']:.0f} m")
        st.caption(f"Distância geral somada ({len(stats['all'])} pares): **{stats['sum_all']:,.0f} m**"
                   .replace(",", "."))
        st.plotly_chart(ui.fig_distance_hist(stats, bins=h_bins, which=h_which), key="fig_hist", theme=None)
if n >= 2:
    with s2[3].expander("Matriz de distâncias (m) e áreas das células"):
        st.dataframe(pd.DataFrame(stats["D"], index=names, columns=names).round(1))
        st.dataframe(pd.DataFrame({"Ponto": names, "Área da célula (%)": r["area_v"].round(1),
                                   "Vizinho mais próximo (m)": stats["nearest"].round(1)}), hide_index=True)

# 3 · Power-Voronoi
chart(s3[0], ui.fig_power(r, show_circles=p3_circles, show_marks=p3_marks, opacity=p3_opacity), "fig_power")
with s3[1]:
    m = st.columns(2)
    m[0].metric("Voronoi × sinal real", f"{r['acc_v']:.1f} %",
                help="% da área em que a célula geométrica coincide com a torre de melhor sinal.")
    m[1].metric("Power-Voronoi × sinal real", f"{r['acc_p']:.1f} %", delta=f"{r['acc_p'] - r['acc_v']:+.1f} pp")
    m[0].metric("Área coberta", f"{r['covered']:.1f} %", help="Área com RSRP ≥ mínimo.")
    empties = [label(i) for i, cell in enumerate(r["pdiag"].cells) if cell.empty]
    m[1].metric("Células vazias", str(len(empties)))
    st.caption("Peso: " + r["w_expl"])
    if empties:
        distorted = [label(i) for i, cell in enumerate(r["pdiag"].cells) if cell.empty and r["area_real"][i] >= 0.5]
        verb = "ficaram" if len(empties) > 1 else "ficou"
        msg = (f"{', '.join(empties)} {verb} sem célula: uma torre vizinha mais forte domina toda a região. "
               "Isso é possível no Power-Voronoi — e no mundo real, quando uma macro 'engole' uma small cell.")
        if distorted:
            msg += (f" Porém no sinal real {', '.join(distorted)} ainda serve(m) usuários: aqui o sumiço é "
                    "distorção do modelo de peso, não da rede.")
        st.warning(msg)
    st.markdown("**Torres (pesos)**")
    st.dataframe(pd.DataFrame({
        "Torre": names, "Classe": [geo.tower_class(p) for p in r["ptx"]], "Potência Tx (dBm)": r["ptx"],
        "Raio (m)": r["radii"].round(0), "Peso w (m²)": r["weights"].round(0),
        "Área Voronoi (%)": r["area_v"].round(1), "Área Power (%)": r["area_p"].round(1),
        "Área atendida (%)": r["area_served"].round(1),
    }), hide_index=True)
with s3[3]:
    st.markdown("**Fronteiras entre torres** · deslocamento > 0 = fronteira empurrada para longe de Pi "
                "(Pi é mais forte)")
    if r["boundaries"]:
        st.dataframe(pd.DataFrame([{
            "Fronteira": f"{label(b['i'])} | {label(b['j'])}", "Distância (m)": round(b["d"], 1),
            "Voronoi: a partir de Pi (m)": round(b["d"] / 2, 1), "Power: a partir de Pi (m)": round(b["t_pow"], 1),
            "Sinal real: a partir de Pi (m)": round(b["t_real"], 1),
            "Deslocamento Power (m)": round(b["t_pow"] - b["d"] / 2, 1),
            "Comprimento da fronteira (m)": round(b["length"], 1)} for b in r["boundaries"]]), hide_index=True)
    else:
        st.caption("Sem fronteiras: só há uma célula não vazia.")

# 4 · Sinal real
chart(s4[0], ui.fig_real(r, ctrl["threshold"], step=r_step, show_power_borders=r_borders,
                         show_contours=r_contours), "fig_real")
with s4[1]:
    prx = r["grid"]["best_prx"]
    m = st.columns(2)
    m[0].metric("Área coberta", f"{r['covered']:.1f} %", help="Área com RSRP ≥ mínimo (dentro da linha vermelha).")
    m[1].metric("Power-Voronoi acerta", f"{r['acc_p']:.1f} %", help="Mesma métrica do gráfico 3.")
    m[0].metric("RSRP mediano", f"{np.median(prx):.1f} dBm", help="Sinal típico no terreno.")
    m[1].metric("RSRP na borda (10 %)", f"{np.percentile(prx, 10):.1f} dBm",
                help="10 % da área tem sinal pior que este valor.")
    st.markdown("**Área servida por torre (%)**")
    st.dataframe(pd.DataFrame({"Torre": names, "Sinal real": r["area_real"].round(1),
                               "Power-Voronoi": r["area_p"].round(1), "Voronoi": r["area_v"].round(1)}),
                 hide_index=True)

# 5 · Rede e canais
chart(s5[0], ui.fig_network(r, show_graph=n_graph, show_ues=n_ues), "fig_network")
with s5[1]:
    m = st.columns(2)
    m[0].metric("Canais usados", f"{len(set(r['alloc'].tolist()))} de {ctrl['n_channels']}")
    m[1].metric("Vizinhos no mesmo canal", str(len(r["conflicts"])), help="Pares de células vizinhas que interferem.")
    total_w = sum(r["edges"].values())
    clash_w = sum(r["edges"][e] for e in r["conflicts"])
    m[0].metric("Interferência residual", f"{100 * clash_w / total_w:.0f} %" if total_w else "—",
                help="Peso dos vizinhos no mesmo canal ÷ peso total do grafo (0 % = nenhum conflito).")
    m[1].metric("Carga máxima", f"{r['loads'].max():.0f} UEs", help="Usuários na célula mais carregada.")
    clash_of = {i: [label(v if u == i else u) for u, v in r["conflicts"] if i in (u, v)] for i in range(n)}
    st.dataframe(pd.DataFrame({
        "Torre": names, "Canal": [f"f{f}" for f in r["alloc"]], "Carga (UEs)": r["loads"].astype(int),
        "Mesmo canal que": [", ".join(clash_of[i]) or "—" for i in range(n)],
    }), hide_index=True)
    st.caption("Configuração alocada: " + " · ".join(f"{label(g)}→f{f}" for g, f in enumerate(r["alloc"])))

# 6 · SINR
chart(s6[0], ui.fig_sinr(r, ctrl["outage_db"], bins=s_bins), "fig_sinr")
with s6[1]:
    m = st.columns(2)
    m[0].metric("SINR médio", f"{ev['mean_sinr']:.2f} dB")
    m[1].metric("Taxa de outage", f"{ev['outage']:.1f} %", help=f"UEs com SINR < {ctrl['outage_db']:.1f} dB.")
    m[0].metric("Throughput médio", f"{ev['mean_tp']:.2f} Mbps")
    m[1].metric("Equidade (Jain)", f"{ev['jain']:.3f}", help="1 = todos os usuários com a mesma taxa.")
    m[0].metric("UEs sem cobertura", f"{r['no_cov']:.1f} %", help="RSRP da torre servidora abaixo do mínimo.")
    m[1].metric("Piso de ruído", f"{ev['noise_dbm']:.1f} dBm", help="−174 dBm/Hz + 10·log₁₀(B) + NF.")
    if ctrl["n_channels"] == 1 or ctrl["alloc_method"] == "unico":
        st.info("Com um único canal todas as torres interferem entre si — compare com *Minimizar interferência*.")
