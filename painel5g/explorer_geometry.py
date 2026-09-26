"""
explorer_geometry.py — Núcleo geométrico e de rádio do Explorador (Fase 1).

Tudo aqui é numpy puro (sem Streamlit), para poder ser testado isoladamente.

Conceitos
---------
Voronoi clássico
    Célula de P_i = pontos x mais próximos de P_i do que de qualquer P_j.
    Fronteira P_i|P_j = mediatriz do segmento P_i–P_j (sempre no meio, d/2).

Power-Voronoi (diagrama de Laguerre)
    Cada ponto recebe um peso w_i e a "distância de potência" é
        pow_i(x) = |x - P_i|^2 - w_i
    A célula de P_i é onde pow_i é mínima. A fronteira P_i|P_j continua reta
    (é o eixo radical), mas se desloca na direção da torre mais fraca:
        t_i = (d^2 + w_i - w_j) / (2d)     (distância da fronteira até P_i)
    Aqui usamos w_i = r_i^2, onde r_i é o raio de cobertura da torre i obtido
    do modelo de propagação — assim o peso tem significado físico em metros.

Mapa real (best-server)
    Para cada pixel, a torre servidora é a de maior potência recebida
        RSRP_i(x) = Ptx_i + G − 10·log10(12·N_RB) − PL(|x - P_i|)
    Com o modelo log-distância e expoente único, essa fronteira é um arco de
    círculo (Voronoi multiplicativo/Apollonius), não uma reta. O Power-Voronoi
    é a aproximação linear dela; o dashboard mede a concordância entre os dois.

As células são calculadas recortando o retângulo da área por semiplanos
(Sutherland–Hodgman), o que funciona para qualquer quantidade de pontos
(inclusive 1, 2 e 3, onde o scipy.spatial.Voronoi falha ou gera regiões
infinitas) e identifica exatamente qual vizinho gerou cada aresta.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

C_LIGHT = 299_792_458.0  # m/s
_EPS = 1e-9

# Rótulos das bordas do retângulo (negativos para não colidir com índices de pontos)
BORDER_LABEL = -1


# ---------------------------------------------------------------------------
# Geração de pontos e potências
# ---------------------------------------------------------------------------
def generate_points(n: int, area: float, seed: int, margin_frac: float = 0.08) -> np.ndarray:
    """Gera n pontos na área com separação mínima (evita torres sobrepostas)."""
    if n <= 0:
        return np.empty((0, 2))
    rng = np.random.default_rng(int(seed))
    margin = area * margin_frac
    min_sep = 0.5 * area / np.sqrt(n)  # separação alvo proporcional à densidade
    pts: list[np.ndarray] = []
    attempts = 0
    while len(pts) < n:
        cand = rng.uniform(margin, area - margin, size=2)
        attempts += 1
        # após muitas tentativas aceita o candidato (garante término em áreas apertadas)
        if attempts > 5000 or all(np.linalg.norm(cand - p) >= min_sep for p in pts):
            pts.append(cand)
            attempts = 0
    return np.round(np.array(pts), 1)


def generate_tx_powers(n: int, seed: int, lo: float = 30.0, hi: float = 46.0) -> np.ndarray:
    """Potências de transmissão aleatórias (dBm), arredondadas em 0,5 dB."""
    if n <= 0:
        return np.empty(0)
    rng = np.random.default_rng(int(seed))
    return np.round(rng.uniform(lo, hi, size=n) * 2) / 2


def tower_class(ptx_dbm: float) -> str:
    """Classificação didática do porte da estação pela potência."""
    if ptx_dbm >= 43:
        return "Macro"
    if ptx_dbm >= 37:
        return "Micro"
    return "Small cell"


# ---------------------------------------------------------------------------
# Modelo de propagação (log-distância com referência em espaço livre a 1 m)
# ---------------------------------------------------------------------------
def fspl_1m_db(freq_hz: float) -> float:
    """Perda em espaço livre a 1 m: 20·log10(4π f / c)."""
    return 20.0 * np.log10(4.0 * np.pi * freq_hz / C_LIGHT)


def path_loss_db(d_m: np.ndarray, freq_hz: float, n_exp: float) -> np.ndarray:
    """PL(d) = FSPL(1 m) + 10·n·log10(d), com d ≥ 1 m."""
    d = np.maximum(np.asarray(d_m, dtype=float), 1.0)
    return fspl_1m_db(freq_hz) + 10.0 * n_exp * np.log10(d)


def re_power_dbm(ptx_dbm, antenna_gain_dbi: float, n_rb: int) -> np.ndarray:
    """
    Potência por elemento de recurso (base do RSRP no 5G NR):
        P_RE = Ptx + G_antena − 10·log10(12·N_RB)
    A potência total é dividida entre as 12·N_RB subportadoras da portadora.
    """
    return np.asarray(ptx_dbm, dtype=float) + antenna_gain_dbi - 10.0 * np.log10(12 * n_rb)


def coverage_radius_m(p_ref_dbm: np.ndarray, threshold_dbm: float, freq_hz: float, n_exp: float) -> np.ndarray:
    """Distância em que a potência de referência cai até o limiar de cobertura."""
    budget = np.asarray(p_ref_dbm, dtype=float) - threshold_dbm - fspl_1m_db(freq_hz)
    return np.power(10.0, budget / (10.0 * n_exp))


# ---------------------------------------------------------------------------
# Células por recorte de semiplanos
# ---------------------------------------------------------------------------
@dataclass
class Cell:
    """Polígono convexo de uma célula. labels[k] = quem gerou a aresta vertices[k]→vertices[k+1]."""
    vertices: np.ndarray                       # (m, 2)
    labels: np.ndarray                         # (m,) índice do vizinho ou BORDER_LABEL
    area: float = 0.0

    @property
    def empty(self) -> bool:
        return len(self.vertices) < 3 or self.area <= 1e-6


@dataclass
class Diagram:
    points: np.ndarray
    weights: np.ndarray
    area_side: float
    cells: list[Cell] = field(default_factory=list)

    def neighbors(self) -> list[tuple[int, int, float, np.ndarray]]:
        """Pares vizinhos (i<j) com o comprimento e o segmento da fronteira comum."""
        out = []
        for i, cell in enumerate(self.cells):
            if cell.empty:
                continue
            m = len(cell.vertices)
            for k in range(m):
                j = int(cell.labels[k])
                if j > i:
                    a, b = cell.vertices[k], cell.vertices[(k + 1) % m]
                    length = float(np.linalg.norm(b - a))
                    if length > 1e-6:
                        out.append((i, j, length, np.vstack([a, b])))
        return out


def _clip(verts: np.ndarray, labels: np.ndarray, normal: np.ndarray, offset: float, label: int):
    """Mantém a parte do polígono com normal·x ≤ offset (Sutherland–Hodgman com rótulos)."""
    if len(verts) == 0:
        return verts, labels
    vals = verts @ normal - offset
    inside = vals <= _EPS
    new_v, new_l = [], []
    m = len(verts)
    for k in range(m):
        a, b = verts[k], verts[(k + 1) % m]
        va, vb = vals[k], vals[(k + 1) % m]
        ia, ib = inside[k], inside[(k + 1) % m]
        if ia:
            new_v.append(a)
            new_l.append(labels[k])
        if ia != ib:
            t = va / (va - vb)
            p = a + t * (b - a)
            new_v.append(p)
            # saindo da região: a próxima aresta corre sobre a reta de corte
            new_l.append(label if ia else labels[k])
    if len(new_v) < 3:
        return np.empty((0, 2)), np.empty(0, dtype=int)
    return np.array(new_v), np.array(new_l, dtype=int)


def _polygon_area(v: np.ndarray) -> float:
    if len(v) < 3:
        return 0.0
    x, y = v[:, 0], v[:, 1]
    return 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def power_diagram(points: np.ndarray, weights: np.ndarray | None, area_side: float) -> Diagram:
    """
    Calcula o diagrama de potência dentro de [0, L]².
    weights=None (ou todos iguais) → Voronoi clássico.

    Semiplano de P_i contra P_j:  2(P_j − P_i)·x ≤ |P_j|² − |P_i|² − w_j + w_i
    """
    pts = np.asarray(points, dtype=float)
    n = len(pts)
    w = np.zeros(n) if weights is None else np.asarray(weights, dtype=float)
    L = float(area_side)
    box = np.array([[0.0, 0.0], [L, 0.0], [L, L], [0.0, L]])
    box_labels = np.full(4, BORDER_LABEL, dtype=int)

    diag = Diagram(points=pts, weights=w, area_side=L)
    sq = np.sum(pts ** 2, axis=1)
    for i in range(n):
        v, lab = box.copy(), box_labels.copy()
        for j in range(n):
            if j == i:
                continue
            normal = 2.0 * (pts[j] - pts[i])
            offset = sq[j] - sq[i] - w[j] + w[i]
            v, lab = _clip(v, lab, normal, offset, j)
            if len(v) == 0:
                break
        diag.cells.append(Cell(vertices=v, labels=lab, area=_polygon_area(v)))
    return diag


def boundary_offset_from_i(p_i: np.ndarray, p_j: np.ndarray, w_i: float, w_j: float) -> float:
    """Distância (ao longo do segmento P_i→P_j) até onde a fronteira de potência cruza a reta."""
    d = float(np.linalg.norm(p_j - p_i))
    return (d * d + w_i - w_j) / (2.0 * d) if d > 0 else 0.0


# ---------------------------------------------------------------------------
# Estatísticas de distância
# ---------------------------------------------------------------------------
def distance_matrix(points: np.ndarray) -> np.ndarray:
    diff = points[:, None, :] - points[None, :, :]
    return np.sqrt(np.sum(diff ** 2, axis=-1))


def distance_stats(points: np.ndarray, neighbor_pairs: list[tuple[int, int]]) -> dict:
    """Média/mediana geral (todos os pares), entre vizinhos Voronoi e ao vizinho mais próximo."""
    n = len(points)
    if n < 2:
        return {}
    D = distance_matrix(points)
    iu = np.triu_indices(n, k=1)
    all_d = D[iu]
    D_nn = D + np.diag(np.full(n, np.inf))
    nn = D_nn.min(axis=1)
    neigh_d = np.array([D[i, j] for i, j in neighbor_pairs]) if neighbor_pairs else np.empty(0)
    return {
        "D": D,
        "all": all_d,
        "neighbors": neigh_d,
        "nearest": nn,
        "mean_all": float(all_d.mean()),
        "median_all": float(np.median(all_d)),
        "min_all": float(all_d.min()),
        "max_all": float(all_d.max()),
        "sum_all": float(all_d.sum()),
        "mean_neighbors": float(neigh_d.mean()) if neigh_d.size else float("nan"),
        "median_neighbors": float(np.median(neigh_d)) if neigh_d.size else float("nan"),
        "mean_nearest": float(nn.mean()),
        "median_nearest": float(np.median(nn)),
    }


# ---------------------------------------------------------------------------
# Mapa de cobertura (grade)
# ---------------------------------------------------------------------------
def coverage_grid(points, p_ref_dbm, weights, area_side, freq_hz, n_exp, threshold_dbm=-np.inf,
                  res: int = 220) -> dict:
    """
    Best-server real (maior potência recebida) e atribuições Voronoi/Power na mesma grade.
    As máscaras *_covered indicam onde a torre atribuída chega com sinal ≥ limiar.
    """
    L = float(area_side)
    xs = (np.arange(res) + 0.5) * L / res
    X, Y = np.meshgrid(xs, xs)
    grid = np.stack([X.ravel(), Y.ravel()], axis=1)
    d2 = np.sum((grid[:, None, :] - points[None, :, :]) ** 2, axis=-1)  # (res², n) — n ≤ 10
    prx = np.asarray(p_ref_dbm)[None, :] - path_loss_db(np.sqrt(d2), freq_hz, n_exp)
    rows = np.arange(len(grid))
    best = np.argmax(prx, axis=1)
    vor = np.argmin(d2, axis=1)
    powr = np.argmin(d2 - np.asarray(weights)[None, :], axis=1)
    shape = (res, res)
    return {
        "xs": xs,
        "extent": (0.0, L, 0.0, L),
        "best_server": best.reshape(shape),
        "best_prx": prx[rows, best].reshape(shape),
        "voronoi": vor.reshape(shape),
        "power": powr.reshape(shape),
        "best_covered": (prx[rows, best] >= threshold_dbm).reshape(shape),
        "power_covered": (prx[rows, powr] >= threshold_dbm).reshape(shape),
    }
