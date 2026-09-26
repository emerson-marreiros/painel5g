"""
radio.py — Usuários, alocação de canais e desempenho de rádio (numpy puro, sem Streamlit).

Usa as MESMAS torres (posição + potência Tx) e o MESMO modelo de propagação do
Power-Voronoi, para que todos os gráficos do painel descrevam a mesma rede.

Fluxo
-----
1. Usuários (UEs): parte concentrada num hotspot em torno de uma torre, parte uniforme.
2. Cada UE é servido pela torre de maior potência recebida (melhor servidor).
3. Grafo de interferência: torres vizinhas no Power-Voronoi, com peso
       w_uv = (carga_u + carga_v) / distância_uv
4. Alocação de canais: heurística gulosa + refinamento local que minimiza a soma
   dos pesos entre vizinhos no mesmo canal (ou aleatória, para comparação).
5. SINR = S / (I_co-canal + N), N = −174 dBm/Hz + 10·log10(B) + NF.
   Throughput (Shannon) = B·log2(1 + SINR). Equidade de Jain sobre o throughput.
"""

from __future__ import annotations

import numpy as np

import explorer_geometry as geo


def generate_users(n_users: int, hotspot_frac: float, center: np.ndarray, area: float, seed: int,
                   spread: float = 80.0) -> np.ndarray:
    rng = np.random.default_rng(int(seed))
    n_hot = int(round(n_users * hotspot_frac))
    hot = rng.normal(np.asarray(center, dtype=float) + rng.normal(0, 50, size=2), spread, size=(n_hot, 2))
    uni = rng.uniform(0, area, size=(n_users - n_hot, 2))
    return np.vstack([hot, uni]).clip(0, area)


def received_power_dbm(points, ptx_dbm, users, gain_dbi, freq_hz, n_exp) -> np.ndarray:
    """Potência total recebida (dBm) de cada torre em cada UE — matriz (n_ues, n_torres)."""
    d = np.linalg.norm(users[:, None, :] - points[None, :, :], axis=-1)
    return np.asarray(ptx_dbm)[None, :] + gain_dbi - geo.path_loss_db(d, freq_hz, n_exp)


def interference_graph(points, loads, neighbor_pairs) -> dict[tuple[int, int], float]:
    out = {}
    for i, j in neighbor_pairs:
        d = float(np.linalg.norm(points[i] - points[j]))
        out[(min(i, j), max(i, j))] = (loads[i] + loads[j]) / (d + 1e-5)
    return out


def _conflict(alloc, edges) -> float:
    return sum(w for (u, v), w in edges.items() if alloc[u] == alloc[v])


def allocate_channels(n: int, n_channels: int, edges: dict, method: str = "otimizada", seed: int = 0) -> np.ndarray:
    """Canal (0…F−1) de cada torre. 'otimizada' minimiza a interferência co-canal ponderada."""
    if method == "aleatoria":
        return np.random.default_rng(int(seed)).integers(0, n_channels, size=n)
    if method == "unico":
        return np.zeros(n, dtype=int)
    adj = [dict() for _ in range(n)]
    for (u, v), w in edges.items():
        adj[u][v] = w
        adj[v][u] = w
    order = sorted(range(n), key=lambda i: -sum(adj[i].values()))
    alloc = np.full(n, -1)

    def cost(i, f):
        return sum(w for j, w in adj[i].items() if alloc[j] == f)

    for i in order:  # guloso: torre mais "disputada" escolhe primeiro
        alloc[i] = min(range(n_channels), key=lambda f: (cost(i, f), f))
    for _ in range(20):  # refinamento local: troca de canal enquanto melhorar
        improved = False
        for i in order:
            best = min(range(n_channels), key=lambda f: (cost(i, f), f != alloc[i], f))
            if cost(i, best) < cost(i, alloc[i]) - 1e-12:
                alloc[i] = best
                improved = True
        if not improved:
            break
    return alloc


def noise_dbm(bw_mhz: float, nf_db: float) -> float:
    return -174.0 + 10.0 * np.log10(bw_mhz * 1e6) + nf_db


def evaluate(prx_dbm: np.ndarray, alloc: np.ndarray, bw_mhz: float, nf_db: float, outage_db: float) -> dict:
    """SINR, outage, throughput e equidade para UEs servidos pelo melhor servidor."""
    n_ue = prx_dbm.shape[0]
    serving = np.argmax(prx_dbm, axis=1)
    p_mw = 10 ** (prx_dbm / 10)
    rows = np.arange(n_ue)
    signal = p_mw[rows, serving]
    same = alloc[None, :] == alloc[serving][:, None]
    same[rows, serving] = False
    interf = np.sum(p_mw * same, axis=1)
    n_mw = 10 ** (noise_dbm(bw_mhz, nf_db) / 10)
    sinr_db = 10 * np.log10(signal / (interf + n_mw))
    tp = bw_mhz * np.log2(1 + 10 ** (sinr_db / 10))  # Mbps
    return {
        "serving": serving,
        "sinr_db": sinr_db,
        "throughput": tp,
        "mean_sinr": float(np.mean(sinr_db)),
        "outage": float(100 * np.mean(sinr_db < outage_db)),
        "mean_tp": float(np.mean(tp)),
        "jain": float(np.sum(tp) ** 2 / (n_ue * np.sum(tp ** 2) + 1e-9)),
        "noise_dbm": noise_dbm(bw_mhz, nf_db),
    }
