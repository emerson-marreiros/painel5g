"""Testes do solver QUBO. Rodar com:  python -m pytest -q"""
import itertools

import numpy as np
import pytest

import qubo_solver as qs


def _brute(Q):
    n = Q.shape[0]
    return min(float(np.array(b) @ Q @ np.array(b)) for b in itertools.product([0, 1], repeat=n))


@pytest.mark.parametrize("seed", range(5))
def test_exact_matches_brute_force(seed):
    Q = np.random.default_rng(seed).normal(size=(10, 10))
    Q = (Q + Q.T) / 2
    r = qs.solve_qubo(Q)
    assert r.method == "exato"
    assert r.energy == pytest.approx(_brute(Q))
    assert qs.energy(Q, r.x) == pytest.approx(r.energy)


def _allocation_qubo(n_gnb, n_f, A, B, seed):
    """Mesmo formato do app: one-hot por gNodeB (A) + interferência co-canal entre vizinhos (B)."""
    rng = np.random.default_rng(seed)
    n = n_gnb * n_f
    Q = np.zeros((n, n))
    idx = lambda g, f: g * n_f + f
    for g in range(n_gnb):
        for f in range(n_f):
            Q[idx(g, f), idx(g, f)] -= A
        for f1, f2 in itertools.combinations(range(n_f), 2):
            Q[idx(g, f1), idx(g, f2)] += 2 * A
            Q[idx(g, f2), idx(g, f1)] += 2 * A
    for u, v in itertools.combinations(range(n_gnb), 2):
        if rng.random() < 0.5:
            w = rng.uniform(0.2, 3.0)
            for f in range(n_f):
                Q[idx(u, f), idx(v, f)] += B * w
                Q[idx(v, f), idx(u, f)] += B * w
    return Q


@pytest.mark.parametrize("seed", range(6))
def test_annealing_finds_optimum_on_allocation_problems(seed):
    Q = _allocation_qubo(6, 3, 15.0, 3.0, seed)  # 18 variáveis: dá para comparar com o exato
    exact = qs._solve_exact(Q)
    heur = qs._solve_annealing(Q, seed)
    assert heur.energy == pytest.approx(exact.energy, abs=1e-6)


def test_large_problem_uses_annealing_and_assigns_every_gnb():
    Q = _allocation_qubo(12, 4, 15.0, 3.0, 1)  # 48 variáveis
    r = qs.solve_qubo(Q, seed=1)
    assert r.method == "annealing"
    assert (r.x.reshape(12, 4).sum(axis=1) == 1).all()  # one-hot respeitado
