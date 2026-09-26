"""
qubo_solver.py — Minimiza E(x) = xᵀ Q x com x ∈ {0,1}ⁿ.

Substitui o laço original, que testava só as primeiras 2048 combinações
(`min(2**n, 2048)`). Com 8 gNodeBs × 3 canais (24 variáveis) isso cobria
0,01% do espaço e os primeiros bits ficavam sempre em zero — por isso mudar
A/B quase não alterava a alocação.

Estratégia
----------
* n ≤ EXACT_LIMIT (22) → enumeração exaustiva vetorizada (ótimo garantido).
* n  > EXACT_LIMIT → simulated annealing com várias cadeias em paralelo
  (numpy), seguido de busca local gulosa. Heurístico, mas reprodutível
  (semente fixa) e validado contra o exato nos testes.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

EXACT_LIMIT = 22  # 2^22 ≈ 4 milhões de configurações — cerca de 0,5 s


@dataclass
class QuboResult:
    x: np.ndarray
    energy: float
    method: str  # "exato" | "annealing"
    evaluated: int


def energy(Q: np.ndarray, x: np.ndarray) -> float:
    return float(x @ Q @ x)


def _solve_exact(Q: np.ndarray, chunk: int = 1 << 15) -> QuboResult:
    n = Q.shape[0]
    total = 1 << n
    shifts = np.arange(n - 1, -1, -1, dtype=np.int64)  # bit mais significativo = variável 0
    best_e, best_x = np.inf, None
    for start in range(0, total, chunk):
        ids = np.arange(start, min(start + chunk, total), dtype=np.int64)
        X = ((ids[:, None] >> shifts) & 1).astype(float)
        E = np.einsum("ij,ij->i", X @ Q, X)
        k = int(np.argmin(E))
        if E[k] < best_e:
            best_e, best_x = float(E[k]), X[k].astype(int)
    return QuboResult(best_x, best_e, "exato", total)


def _local_descent(Qs: np.ndarray, x: np.ndarray) -> np.ndarray:
    """Vira o bit que mais reduz a energia até não haver melhora (mínimo local)."""
    x = x.copy()
    diag = np.diag(Qs)
    while True:
        field = Qs @ x
        s = 1 - 2 * x  # +1 se 0→1, −1 se 1→0
        delta = s * (2 * (field - diag * x) + diag)
        i = int(np.argmin(delta))
        if delta[i] >= -1e-12:
            return x
        x[i] ^= 1


def _solve_annealing(Q: np.ndarray, seed: int, chains: int = 256, sweeps: int = 150) -> QuboResult:
    rng = np.random.default_rng(int(seed))
    n = Q.shape[0]
    Qs = (Q + Q.T) / 2.0
    diag = np.diag(Qs)
    x = rng.integers(0, 2, size=(chains, n))
    field = x @ Qs
    e = np.einsum("ij,ij->i", field, x)
    best_x, best_e = x.copy(), e.copy()

    scale = max(np.abs(Qs).max(), 1e-9)
    steps = sweeps * n
    temps = scale * np.geomspace(2.0, 1e-3, steps)
    rows = np.arange(chains)
    for t in temps:
        i = rng.integers(0, n, size=chains)
        xi = x[rows, i]
        s = 1 - 2 * xi
        delta = s * (2 * (field[rows, i] - diag[i] * xi) + diag[i])
        accept = (delta <= 0) | (rng.random(chains) < np.exp(-np.clip(delta, 0, None) / t))
        if accept.any():
            a = rows[accept]
            x[a, i[accept]] ^= 1
            field[a] += s[accept, None] * Qs[i[accept]]
            e[a] += delta[accept]
            better = e < best_e
            best_x[better], best_e[better] = x[better], e[better]

    # polimento: descida local nas 16 melhores cadeias
    finalists = np.argsort(best_e)[:16]
    polished = [_local_descent(Qs, best_x[k].astype(int)) for k in finalists]
    energies = [energy(Q, p) for p in polished]
    k = int(np.argmin(energies))
    return QuboResult(polished[k], energies[k], "annealing", chains * steps)


def solve_qubo(Q: np.ndarray, seed: int = 0) -> QuboResult:
    Q = np.asarray(Q, dtype=float)
    if Q.shape[0] <= EXACT_LIMIT:
        return _solve_exact(Q)
    return _solve_annealing(Q, seed)
