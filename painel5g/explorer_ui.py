"""
explorer_ui.py — Cálculo e gráficos (Plotly) do painel.

Todos os gráficos recebem o mesmo dicionário `r` (resultado de `compute`), montado a
partir de UM conjunto de torres (posição + potência). Assim, mudar a quantidade de
pontos, a área ou editar uma torre atualiza todos os gráficos de uma vez; cada
gráfico ainda tem opções próprias (argumentos das funções fig_*).

Cada ponto tem um marcador ⓘ: passe o mouse (ou toque) para ver a ficha completa.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from scipy.stats import gaussian_kde

import explorer_geometry as geo
import radio

MAX_POINTS = 10
# 10 cores bem distintas entre si e do cinza usado para "sem cobertura"
PALETTE = ["#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f",
           "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#17d4ff"]
CHANNEL_COLORS = ["#4e79a7", "#f28e2b", "#59a14f", "#b07aa1"]
NO_COVERAGE_BG = "#3a3a3a"

# faixa: (frequência, nº de RBs, largura de banda em MHz) — configuração típica 3GPP TS 38.101
BANDS = {
    "n28 · 700 MHz (20 MHz, 106 RB)": (700e6, 106, 20.0),
    "n78 · 3,5 GHz (100 MHz, 273 RB)": (3.5e9, 273, 100.0),
    "n258 · 26 GHz (100 MHz, 66 RB)": (26e9, 66, 100.0),
}
WEIGHT_MODELS = {
    "Calibrado (recomendado)": "calibrated",
    "Raio de cobertura (w = r²)": "radius",
}
ALLOC_METHODS = {
    "Minimizar interferência": "otimizada",
    "Aleatória": "aleatoria",
    "Canal único (sem reuso)": "unico",
}


def label(i: int) -> str:
    return f"P{i + 1}"


# ---------------------------------------------------------------------------
# Tabela editável (fonte única dos pontos para TODOS os gráficos)
# ---------------------------------------------------------------------------
def _editor_key(ctrl) -> str:
    return f"exp_editor_{ctrl['n']}_{ctrl['seed']}_{ctrl['weight_source']}_{ctrl['power_seed']}_{ctrl['L']:.0f}"


def points_editor(ctrl) -> tuple[np.ndarray, np.ndarray]:
    n, L = ctrl["n"], ctrl["L"]
    pts = geo.generate_points(n, L, ctrl["seed"])
    ptx = (geo.generate_tx_powers(n, ctrl["power_seed"]) if ctrl["weight_source"] == "Aleatória"
           else np.full(n, 40.0))
    base = pd.DataFrame({"Ponto": [label(i) for i in range(n)], "X (m)": pts[:, 0], "Y (m)": pts[:, 1],
                         "Potência Tx (dBm)": ptx})
    key = _editor_key(ctrl)
    st.caption("✏️ **Duplo clique** numa célula, digite e tecle **Enter** — todos os gráficos são recalculados.")
    df = st.data_editor(
        base, key=key, hide_index=True, disabled=["Ponto"],
        column_config={
            "X (m)": st.column_config.NumberColumn(min_value=0.0, max_value=float(L), step=1.0, format="%.1f"),
            "Y (m)": st.column_config.NumberColumn(min_value=0.0, max_value=float(L), step=1.0, format="%.1f"),
            "Potência Tx (dBm)": st.column_config.NumberColumn(
                min_value=20.0, max_value=49.0, step=0.5, format="%.1f",
                help="Small cell ≈ 24–33 · Micro ≈ 37–40 · Macro ≈ 43–46 dBm"),
        },
    )
    if st.button("↺ Restaurar valores gerados", key=f"reset_{key}"):
        st.session_state.pop(key, None)
        st.rerun()
    df = df.fillna({"X (m)": L / 2, "Y (m)": L / 2, "Potência Tx (dBm)": 40.0})
    return (df[["X (m)", "Y (m)"]].to_numpy(dtype=float).clip(0, L),
            df["Potência Tx (dBm)"].to_numpy(dtype=float).clip(20, 49))


def notify_changes(pts, ptx, ctrl) -> None:
    """Aviso rápido do que mudou desde a última execução (confirma que o recálculo aconteceu)."""
    sig = {"pts": np.round(pts, 1).tolist(), "ptx": np.round(ptx, 1).tolist(),
           "ctrl": {k: v for k, v in ctrl.items() if isinstance(v, (int, float, str))}}
    prev = st.session_state.get("_exp_prev_sig")
    st.session_state["_exp_prev_sig"] = sig
    if prev is None or prev == sig:
        return
    msgs = []
    if len(prev["pts"]) == len(sig["pts"]):
        for i, (a, b) in enumerate(zip(prev["ptx"], sig["ptx"])):
            if a != b:
                msgs.append(f"{label(i)}: {a:.1f} → {b:.1f} dBm")
        for i, (a, b) in enumerate(zip(prev["pts"], sig["pts"])):
            if a != b:
                msgs.append(f"{label(i)} movido para ({b[0]:.0f}, {b[1]:.0f})")
    else:
        msgs.append(f"{len(sig['pts'])} ponto(s) em todos os gráficos")
    st.toast("🔄 Gráficos recalculados" + (" — " + "; ".join(msgs[:3]) if msgs else ""))


# ---------------------------------------------------------------------------
# Cálculo (tudo antes de desenhar, para as fichas ⓘ terem todos os dados)
# ---------------------------------------------------------------------------
def compute(pts, ptx, ctrl) -> dict:
    """ctrl: L, gain, n_rb, threshold, freq, n_exp, weight_model, grid_res + parâmetros de rádio."""
    L = ctrl["L"]
    n = len(pts)
    r = {"pts": pts, "ptx": ptx, "n": n, "L": L}
    r["vdiag"] = geo.power_diagram(pts, None, L)
    r["v_neighbors"] = r["vdiag"].neighbors()
    r["stats"] = geo.distance_stats(pts, [(i, j) for i, j, *_ in r["v_neighbors"]])
    r["p_ref"] = geo.re_power_dbm(ptx, ctrl["gain"], ctrl["n_rb"])
    r["radii"] = geo.coverage_radius_m(r["p_ref"], ctrl["threshold"], ctrl["freq"], ctrl["n_exp"])
    d_ref = r["stats"].get("mean_neighbors", float("nan"))
    if ctrl["weight_model"] == "calibrated" and n >= 2 and not np.isnan(d_ref):
        w = (d_ref ** 2 / 2.0) * np.log(r["radii"])
        r["weights"] = w - w.min()  # somar uma constante a todos os pesos não muda o diagrama; assim w ≥ 0
        r["w_expl"] = (f"w = (D̄²/2)·ln(r/r_min), D̄ = média entre vizinhos = {d_ref:.0f} m. A fronteira cai onde o "
                       "sinal das duas torres se iguala — por isso faixa e RSRP mínimo mudam o **alcance** (áreas "
                       "cinza), mas não **quem vence** a fronteira.")
    else:
        r["weights"] = r["radii"] ** 2
        r["w_expl"] = ("w = r² (raio de cobertura ao quadrado). Muda com faixa, ganho e RSRP mínimo, mas tende a "
                       "exagerar torres fortes quando r ≫ distância entre torres.")
    r["pdiag"] = geo.power_diagram(pts, r["weights"], L)
    r["p_neighbors"] = r["pdiag"].neighbors()
    r["grid"] = geo.coverage_grid(pts, r["p_ref"], r["weights"], L, ctrl["freq"], ctrl["n_exp"], ctrl["threshold"],
                                  res=ctrl.get("grid_res", 220))
    g = r["grid"]
    bs = g["best_server"]
    r["acc_v"] = 100 * np.mean(g["voronoi"] == bs)
    r["acc_p"] = 100 * np.mean(g["power"] == bs)
    r["covered"] = 100 * np.mean(g["best_covered"])
    r["area_real"] = np.array([100 * np.mean(bs == i) for i in range(n)])
    r["area_served"] = np.array([100 * np.mean((g["power"] == i) & g["power_covered"]) for i in range(n)])
    r["area_v"] = np.array([100 * c.area / L ** 2 for c in r["vdiag"].cells])
    r["area_p"] = np.array([100 * c.area / L ** 2 for c in r["pdiag"].cells])
    r["boundaries"] = _boundaries(r)
    _compute_radio(r, ctrl)
    r["cards"] = _cards(r, ctrl)
    return r


def _compute_radio(r, ctrl) -> None:
    """Usuários, alocação de canais e SINR — sobre as mesmas torres e o mesmo modelo de propagação."""
    n, pts = r["n"], r["pts"]
    center = pts[min(ctrl["hotspot_tower"], n - 1)]
    ues = radio.generate_users(ctrl["n_users"], ctrl["hotspot"], center, r["L"], ctrl["ue_seed"])
    prx = radio.received_power_dbm(pts, r["ptx"], ues, ctrl["gain"], ctrl["freq"], ctrl["n_exp"])
    serving = np.argmax(prx, axis=1)
    loads = np.bincount(serving, minlength=n).astype(float)
    edges = radio.interference_graph(pts, loads, [(i, j) for i, j, *_ in r["p_neighbors"]])
    alloc = radio.allocate_channels(n, ctrl["n_channels"], edges, ctrl["alloc_method"], ctrl["ue_seed"])
    ev = radio.evaluate(prx, alloc, ctrl["bw"], ctrl["nf"], ctrl["outage_db"])
    rsrp_serv = prx[np.arange(len(ues)), serving] - 10 * np.log10(12 * ctrl["n_rb"])
    r.update(ues=ues, loads=loads, edges=edges, alloc=alloc, ev=ev,
             no_cov=float(100 * np.mean(rsrp_serv < ctrl["threshold"])),
             conflicts=[(u, v) for (u, v) in edges if alloc[u] == alloc[v]])


def _boundaries(r) -> list[dict]:
    pts, w, radii = r["pts"], r["weights"], r["radii"]
    out = []
    for i, j, length, seg in r["p_neighbors"]:
        d = float(np.linalg.norm(pts[j] - pts[i]))
        t_pow = geo.boundary_offset_from_i(pts[i], pts[j], w[i], w[j])
        t_real = d * radii[i] / (radii[i] + radii[j])  # onde RSRP_i = RSRP_j sobre a reta Pi–Pj
        xing = pts[i] + (pts[j] - pts[i]) * t_pow / d if 0 < t_pow < d else None
        if xing is not None and not _point_on_segment(xing, seg):
            xing = None
        out.append(dict(i=i, j=j, d=d, t_pow=t_pow, t_real=t_real, length=length, seg=seg, xing=xing))
    return out


def _point_on_segment(x, seg, tol=1.0):
    a, b = seg
    ab = b - a
    t = np.clip(np.dot(x - a, ab) / (np.dot(ab, ab) + 1e-12), 0, 1)
    return np.linalg.norm(a + t * ab - x) < tol


def _cards(r, ctrl) -> list[str]:
    """Ficha ⓘ de cada ponto (HTML do hover do Plotly) — reúne dados de todos os gráficos."""
    n, pts, ptx, stats = r["n"], r["pts"], r["ptx"], r["stats"]
    vnb = {i: [] for i in range(n)}
    for i, j, *_ in r["v_neighbors"]:
        vnb[i].append(j)
        vnb[j].append(i)
    cards = []
    for i in range(n):
        lines = [f"<b>{label(i)} · {geo.tower_class(ptx[i])}</b>",
                 f"Posição: ({pts[i, 0]:.0f}, {pts[i, 1]:.0f}) m",
                 f"Potência Tx: {ptx[i]:.1f} dBm · EIRP {ptx[i] + ctrl['gain']:.1f} dBm",
                 f"Potência por RE: {r['p_ref'][i]:.1f} dBm",
                 f"Raio de cobertura: {r['radii'][i]:.0f} m",
                 f"Peso Power-Voronoi: {r['weights'][i]:,.0f} m²".replace(",", ".")]
        if n >= 2:
            D = stats["D"][i].copy()
            D[i] = np.inf
            k = int(np.argmin(D))
            lines.append(f"Vizinho mais próximo: {label(k)} ({D[k]:.0f} m)")
            if vnb[i]:
                lines.append("Vizinhos Voronoi: " + ", ".join(f"{label(j)} ({stats['D'][i, j]:.0f} m)"
                                                            for j in sorted(vnb[i])))
        lines += ["─────────",
                  f"Área Voronoi: {r['area_v'][i]:.1f} %",
                  f"Área Power-Voronoi: {r['area_p'][i]:.1f} %",
                  f"Área atendida (com sinal): {r['area_served'][i]:.1f} %",
                  f"Área no sinal real: {r['area_real'][i]:.1f} %",
                  "─────────",
                  f"Canal alocado: f{r['alloc'][i]} · carga {r['loads'][i]:.0f} usuário(s)"]
        clash = [label(v if u == i else u) for u, v in r["conflicts"] if i in (u, v)]
        if clash:
            lines.append("⚠ mesmo canal que vizinho(s): " + ", ".join(clash))
        if r["pdiag"].cells[i].empty:
            lines.append("<i>⚠ sem célula no Power-Voronoi</i>")
        cards.append("<br>".join(lines))
    return cards


# ---------------------------------------------------------------------------
# Plotly
# ---------------------------------------------------------------------------
def _fig(L, title, height=540) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        template="plotly_dark", paper_bgcolor="#0e1117", font=dict(color="#e6e6e6"),
        title=dict(text=title, font=dict(size=15)), height=height,
        margin=dict(l=10, r=10, t=45, b=10), plot_bgcolor="#111418",
        legend=dict(orientation="h", yanchor="top", y=-0.08, x=0, font=dict(size=11)),
        hoverlabel=dict(bgcolor="#1e222a", font=dict(size=12, color="white"), align="left"),
        uirevision="explorer",  # mantém zoom/pan entre recálculos
    )
    fig.update_xaxes(range=[0, L], title="x (m)", showgrid=True, gridcolor="#2a2f38", zeroline=False,
                     constrain="domain")
    fig.update_yaxes(range=[0, L], title="y (m)", showgrid=True, gridcolor="#2a2f38", zeroline=False,
                     scaleanchor="x", scaleratio=1, constrain="domain")
    fig.add_shape(type="rect", x0=0, y0=0, x1=L, y1=L, line=dict(color="#888", width=1))
    return fig


def _add_points(fig, r, sized=False, with_power=False, colors=None):
    """Pontos coloridos + rótulo P# + marcador ⓘ com a ficha completa no hover."""
    pts, ptx, L = r["pts"], r["ptx"], r["L"]
    sizes = 10 + (ptx - 20) * 0.75 if sized else np.full(r["n"], 16)
    texts = [f"{label(i)} · {ptx[i]:.1f} dBm" if with_power else label(i) for i in range(r["n"])]
    fig.add_trace(go.Scatter(
        x=pts[:, 0], y=pts[:, 1], mode="markers+text", text=texts, textposition="top left",
        textfont=dict(size=12, color="white"), name="Torres",
        marker=dict(size=sizes, color=colors or PALETTE[: r["n"]], line=dict(color="black", width=1.5)),
        customdata=r["cards"], hovertemplate="%{customdata}<extra></extra>", showlegend=False,
        cliponaxis=False))
    off = 0.03 * L
    fig.add_trace(go.Scatter(
        x=pts[:, 0] + off, y=pts[:, 1] + off, mode="markers+text", text=["i"] * r["n"],
        textposition="middle center", textfont=dict(size=11, color="white", family="Georgia, serif"),
        marker=dict(size=17, color="#2d6cdf", line=dict(color="white", width=1.5)),
        name="ⓘ ficha do ponto (passe o mouse)", customdata=r["cards"],
        hovertemplate="%{customdata}<extra></extra>"))


def _add_cells(fig, diag, opacity=0.30, boundary_color="white", dash="solid", fill=True, name="Fronteira",
               colors=None):
    if fill:
        for i, cell in enumerate(diag.cells):
            if cell.empty:
                continue
            v = np.vstack([cell.vertices, cell.vertices[:1]])
            fig.add_trace(go.Scatter(x=v[:, 0], y=v[:, 1], fill="toself", fillcolor=(colors or PALETTE)[i],
                                     opacity=opacity, line=dict(width=0), mode="lines", hoverinfo="skip",
                                     showlegend=False))
    xs, ys = [], []
    for _, _, _, seg in diag.neighbors():
        xs += [seg[0, 0], seg[1, 0], None]
        ys += [seg[0, 1], seg[1, 1], None]
    if xs:
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", line=dict(color=boundary_color, width=2.2, dash=dash),
                                 name=name, hoverinfo="skip"))


def _add_coverage_circles(fig, r, opacity=0.8):
    for i, (p, rad) in enumerate(zip(r["pts"], r["radii"])):
        fig.add_shape(type="circle", x0=p[0] - rad, y0=p[1] - rad, x1=p[0] + rad, y1=p[1] + rad,
                      line=dict(color=PALETTE[i], width=1.4, dash="dash"), opacity=opacity)
    fig.add_trace(go.Scatter(x=[None], y=[None], mode="lines", line=dict(color="#aaa", dash="dash"),
                             name="Raio de cobertura"))


def _discrete_heatmap(fig, z, mask, xs, n, opacity):
    z = np.where(mask, z, np.nan).astype(float)
    scale = []
    for k in range(n):
        scale += [[k / n, PALETTE[k]], [(k + 1) / n, PALETTE[k]]]
    if n == 1:
        scale = [[0, PALETTE[0]], [1, PALETTE[0]]]
    fig.add_trace(go.Heatmap(x=xs, y=xs, z=z, zmin=-0.5, zmax=n - 0.5, colorscale=scale, opacity=opacity,
                             showscale=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=[None], y=[None], mode="markers", marker=dict(symbol="square", size=12,
                             color=NO_COVERAGE_BG), name="Sem cobertura"))


# 1 · Pontos -----------------------------------------------------------------
def fig_points(r, show_circles=True, size_by_power=True):
    fig = _fig(r["L"], f"1 · {r['n']} torre(s) identificada(s)")
    if show_circles:
        _add_coverage_circles(fig, r, opacity=0.5)
    _add_points(fig, r, sized=size_by_power, with_power=True)
    return fig


# 2 · Voronoi ----------------------------------------------------------------
def fig_voronoi(r, show_links=True, show_dist=True, fill=True):
    pts = r["pts"]
    fig = _fig(r["L"], "2 · Voronoi clássico (fronteira = mediatriz)")
    _add_cells(fig, r["vdiag"], fill=fill, name="Fronteira (mediatriz)")
    lx, ly, mx, my, mt, mh = [], [], [], [], [], []
    for i, j, length, _ in r["v_neighbors"]:
        a, b = pts[i], pts[j]
        d = np.linalg.norm(b - a)
        lx += [a[0], b[0], None]
        ly += [a[1], b[1], None]
        mx.append((a[0] + b[0]) / 2)
        my.append((a[1] + b[1]) / 2)
        mt.append(f"{d:.0f} m")
        mh.append(f"<b>{label(i)} – {label(j)}</b><br>Distância: {d:.1f} m<br>Fronteira a {d / 2:.1f} m de cada um"
                  f"<br>Comprimento da fronteira: {length:.0f} m")
    if lx and show_links:
        fig.add_trace(go.Scatter(x=lx, y=ly, mode="lines", line=dict(color="#bbb", width=1, dash="dot"),
                                 name="Ligação entre vizinhos", hoverinfo="skip"))
    if mx and show_dist:
        fig.add_trace(go.Scatter(x=mx, y=my, mode="text", text=mt, textfont=dict(size=10, color="#e8e8e8"),
                                 hovertext=mh, hovertemplate="%{hovertext}<extra></extra>", showlegend=False))
    _add_points(fig, r)
    return fig


def fig_distance_hist(stats, bins=8, which="Ambos"):
    fig = go.Figure()
    if which in ("Ambos", "Todos os pares"):
        fig.add_trace(go.Histogram(x=stats["all"], name="Todos os pares", marker_color="#4aa3df", opacity=0.75,
                                   nbinsx=bins))
    if stats["neighbors"].size and which in ("Ambos", "Só vizinhos"):
        fig.add_trace(go.Histogram(x=stats["neighbors"], name="Vizinhos Voronoi", marker_color="#f5b041",
                                   opacity=0.65, nbinsx=bins))
    for val, color, dash, txt in [(stats["mean_all"], "#e74c3c", "dash", "média"),
                                  (stats["median_all"], "#2ecc71", "dashdot", "mediana")]:
        fig.add_vline(x=val, line=dict(color=color, dash=dash, width=2),
                      annotation_text=f"{txt} {val:.0f} m", annotation_font_color=color)
    fig.update_layout(template="plotly_dark", paper_bgcolor="#0e1117", font=dict(color="#e6e6e6"),
                      plot_bgcolor="#111418", barmode="overlay", height=300, margin=dict(l=10, r=10, t=35, b=10),
                      title=dict(text="Distribuição das distâncias", font=dict(size=13)),
                      xaxis_title="distância (m)", yaxis_title="nº de pares",
                      legend=dict(orientation="h", y=-0.3))
    return fig


# 3 · Power-Voronoi ----------------------------------------------------------
def _add_boundary_marks(fig, r):
    xs, ys, hs = [], [], []
    for b in r["boundaries"]:
        if b["xing"] is None:
            continue
        i, j, d = b["i"], b["j"], b["d"]
        xs.append(b["xing"][0])
        ys.append(b["xing"][1])
        hs.append(f"<b>Fronteira {label(i)} | {label(j)}</b><br>Distância entre torres: {d:.0f} m<br>"
                  f"Power: {b['t_pow']:.0f} m de {label(i)} · {d - b['t_pow']:.0f} m de {label(j)}<br>"
                  f"Voronoi: {d / 2:.0f} m de cada<br>Sinal real: {b['t_real']:.0f} m de {label(i)}")
    if xs:
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="markers", name="✕ fronteira na linha entre torres",
                                 marker=dict(symbol="x", size=11, color="white", line=dict(color="black", width=1)),
                                 hovertext=hs, hovertemplate="%{hovertext}<extra></extra>"))


def fig_power(r, show_circles=True, show_marks=True, opacity=0.55):
    g = r["grid"]
    fig = _fig(r["L"], "3 · Power-Voronoi 5G (área atendida por torre)")
    fig.update_layout(plot_bgcolor=NO_COVERAGE_BG)
    _discrete_heatmap(fig, g["power"], g["power_covered"], g["xs"], r["n"], opacity=opacity)
    _add_cells(fig, r["pdiag"], fill=False, name="Fronteira (eixo radical)")
    if show_circles:
        _add_coverage_circles(fig, r)
    if show_marks:
        _add_boundary_marks(fig, r)
    _add_points(fig, r, sized=True, with_power=True)
    return fig


# 4 · Sinal real -------------------------------------------------------------
def fig_real(r, threshold, step=10, show_power_borders=True, show_contours=True):
    g = r["grid"]
    fig = _fig(r["L"], "4 · Sinal real (melhor servidor) × fronteiras Power-Voronoi")
    fig.update_layout(plot_bgcolor=NO_COVERAGE_BG)
    _discrete_heatmap(fig, g["best_server"], g["best_covered"], g["xs"], r["n"], opacity=0.5)
    if show_contours:
        fig.add_trace(go.Contour(x=g["xs"], y=g["xs"], z=g["best_prx"], showscale=False, hoverinfo="skip",
                                 contours=dict(coloring="lines", showlabels=True, start=-140, end=0, size=step,
                                               labelfont=dict(size=9, color="#ddd")),
                                 line=dict(width=0.6), colorscale=[[0, "#cccccc"], [1, "#cccccc"]],
                                 name="RSRP (dBm)", showlegend=True))
    fig.add_trace(go.Contour(x=g["xs"], y=g["xs"], z=g["best_prx"], showscale=False, hoverinfo="skip",
                             contours=dict(coloring="lines", start=threshold, end=threshold, size=1),
                             line=dict(width=2.5), colorscale=[[0, "#ff4d4d"], [1, "#ff4d4d"]],
                             name=f"Limite de cobertura ({threshold:.0f} dBm)", showlegend=True))
    if show_power_borders:
        _add_cells(fig, r["pdiag"], fill=False, dash="dash", name="Fronteira Power-Voronoi")
    _add_points(fig, r)
    return fig


# 5 · Rede e canais ----------------------------------------------------------
def fig_network(r, show_graph=True, show_ues=True):
    """Células Power-Voronoi coloridas pelo canal alocado + usuários + grafo de interferência."""
    pts, alloc = r["pts"], r["alloc"]
    ch_colors = [CHANNEL_COLORS[f % len(CHANNEL_COLORS)] for f in alloc]
    fig = _fig(r["L"], f"5 · Rede: {r['n']} célula(s) · cor = canal alocado")
    _add_cells(fig, r["pdiag"], opacity=0.28, boundary_color="cyan", dash="dash", name="Fronteira da célula",
               colors=ch_colors)
    if show_graph and r["edges"]:
        wmax = max(r["edges"].values()) or 1.0
        for (u, v), w in r["edges"].items():
            clash = alloc[u] == alloc[v]
            fig.add_trace(go.Scatter(
                x=[pts[u, 0], pts[v, 0]], y=[pts[u, 1], pts[v, 1]], mode="lines", hoverinfo="skip",
                line=dict(color="#ff4d4d" if clash else "white", width=1 + 4 * w / wmax,
                          dash="solid" if clash else "dot"),
                opacity=0.85 if clash else 0.45, showlegend=False))
        fig.add_trace(go.Scatter(x=[None], y=[None], mode="lines", line=dict(color="white", dash="dot"),
                                 name="Vizinhos em canais diferentes"))
        fig.add_trace(go.Scatter(x=[None], y=[None], mode="lines", line=dict(color="#ff4d4d"),
                                 name="⚠ Vizinhos no mesmo canal"))
    if show_ues:
        ues = r["ues"]
        fig.add_trace(go.Scatter(x=ues[:, 0], y=ues[:, 1], mode="markers", name="Usuários (UEs)",
                                 marker=dict(size=5, color="magenta", opacity=0.5),
                                 customdata=np.column_stack([[label(s) for s in r["ev"]["serving"]],
                                                             np.round(r["ev"]["sinr_db"], 1)]),
                                 hovertemplate="UE servido por %{customdata[0]}<br>SINR %{customdata[1]} dB"
                                               "<extra></extra>"))
    for f in sorted(set(alloc.tolist())):
        fig.add_trace(go.Scatter(x=[None], y=[None], mode="markers", name=f"Canal f{f}",
                                 marker=dict(symbol="square", size=12, color=CHANNEL_COLORS[f % 4])))
    _add_points(fig, r, colors=ch_colors)
    return fig


# 6 · SINR -------------------------------------------------------------------
def fig_sinr(r, outage_db, bins=30):
    s = r["ev"]["sinr_db"]
    fig = go.Figure()
    fig.add_trace(go.Histogram(x=s, nbinsx=bins, marker_color="skyblue", opacity=0.75, name="UEs",
                               marker_line=dict(color="#0e1117", width=0.5)))
    if len(s) > 2 and np.ptp(s) > 1e-6:
        xs = np.linspace(s.min(), s.max(), 200)
        width = np.ptp(s) / bins
        fig.add_trace(go.Scatter(x=xs, y=gaussian_kde(s)(xs) * len(s) * width, mode="lines",
                                 line=dict(color="skyblue", width=2.5), name="Densidade (KDE)"))
    fig.add_vline(x=outage_db, line=dict(color="red", dash="dash", width=2),
                  annotation_text=f"Limiar de outage ({outage_db:.0f} dB)", annotation_font_color="red")
    fig.update_layout(template="plotly_dark", paper_bgcolor="#0e1117", font=dict(color="#e6e6e6"),
                      plot_bgcolor="#111418", height=440, margin=dict(l=10, r=10, t=45, b=10),
                      title=dict(text="6 · Distribuição do SINR (dB)", font=dict(size=15)),
                      xaxis_title="SINR (dB)", yaxis_title="nº de usuários", bargap=0.05,
                      legend=dict(orientation="h", y=-0.18))
    return fig
