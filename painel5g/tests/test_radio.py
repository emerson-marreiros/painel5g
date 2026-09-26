"""Testes do módulo de rádio (usuários, alocação de canais, SINR). Rodar com:  python -m pytest -q"""
import itertools

import numpy as np
import pytest

import radio


def _cost(alloc, edges):
    return sum(w for (u, v), w in edges.items() if alloc[u] == alloc[v])


@pytest.mark.parametrize("seed", range(8))
def test_optimized_allocation_is_near_optimal(seed):
    rng = np.random.default_rng(seed)
    n, F = 7, 3
    edges = {(u, v): rng.uniform(0.2, 3.0) for u, v in itertools.combinations(range(n), 2) if rng.random() < 0.5}
    best = min(_cost(a, edges) for a in itertools.product(range(F), repeat=n))
    got = _cost(radio.allocate_channels(n, F, edges), edges)
    assert got <= best + 0.25 * sum(edges.values())
    assert got <= _cost(np.zeros(n, dtype=int), edges)


def test_ring_is_colored_without_conflicts():
    edges = {(i, (i + 1) % 6) if i < (i + 1) % 6 else ((i + 1) % 6, i): 1.0 for i in range(6)}
    alloc = radio.allocate_channels(6, 2, edges)
    assert _cost(alloc, edges) == 0


def test_single_channel_has_more_interference_than_reuse():
    pts = np.array([[100.0, 100.0], [400.0, 100.0], [250.0, 350.0]])
    ues = radio.generate_users(200, 0.0, pts[0], 500.0, 0)
    prx = radio.received_power_dbm(pts, np.full(3, 40.0), ues, 15.0, 3.5e9, 3.5)
    one = radio.evaluate(prx, np.zeros(3, dtype=int), 100.0, 7.0, 0.0)
    reuse = radio.evaluate(prx, np.arange(3), 100.0, 7.0, 0.0)
    assert reuse["mean_sinr"] > one["mean_sinr"]
    assert 0 < reuse["jain"] <= 1


def test_noise_floor():
    assert radio.noise_dbm(100.0, 7.0) == pytest.approx(-174 + 80 + 7)
