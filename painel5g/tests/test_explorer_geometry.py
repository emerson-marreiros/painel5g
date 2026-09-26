"""Testes do núcleo geométrico do Explorador. Rodar com:  python -m pytest -q"""
import numpy as np
import pytest

import explorer_geometry as geo

L = 800.0


@pytest.mark.parametrize("n", range(1, 11))
@pytest.mark.parametrize("weighted", [False, True])
def test_cells_partition_the_area(n, weighted):
    for seed in range(10):
        pts = geo.generate_points(n, L, seed)
        w = None
        if weighted:
            r = geo.coverage_radius_m(geo.generate_tx_powers(n, seed + 1), -100, 3.5e9, 3.5)
            w = r ** 2
        diag = geo.power_diagram(pts, w, L)
        assert sum(c.area for c in diag.cells) == pytest.approx(L * L, rel=1e-6)


def test_cells_match_brute_force_grid():
    pts = geo.generate_points(8, L, 3)
    ptx = geo.generate_tx_powers(8, 4)
    w = geo.coverage_radius_m(ptx, -100, 3.5e9, 3.5) ** 2
    diag = geo.power_diagram(pts, w, L)
    grid = geo.coverage_grid(pts, ptx, w, L, 3.5e9, 3.5, res=300)
    frac = np.bincount(grid["power"].ravel(), minlength=8) / grid["power"].size
    areas = np.array([c.area for c in diag.cells]) / L ** 2
    assert np.max(np.abs(frac - areas)) < 0.01


def test_equal_weights_boundary_is_midpoint():
    a, b = np.array([100.0, 100.0]), np.array([500.0, 400.0])
    assert geo.boundary_offset_from_i(a, b, 7.0, 7.0) == pytest.approx(250.0)


def test_stronger_tower_pushes_boundary_away():
    a, b = np.array([0.0, 0.0]), np.array([400.0, 0.0])
    assert geo.boundary_offset_from_i(a, b, 50_000.0, 0.0) > 200.0


def test_distance_stats():
    pts = np.array([[0.0, 0.0], [3.0, 0.0], [0.0, 4.0]])
    s = geo.distance_stats(pts, [(0, 1), (0, 2), (1, 2)])
    assert sorted(s["all"]) == pytest.approx([3.0, 4.0, 5.0])
    assert s["mean_all"] == pytest.approx(4.0)
    assert s["median_all"] == pytest.approx(4.0)
    assert s["sum_all"] == pytest.approx(12.0)
    assert s["mean_nearest"] == pytest.approx((3 + 3 + 4) / 3)


def test_coverage_radius_consistent_with_path_loss():
    r = geo.coverage_radius_m(np.array([46.0]), -100.0, 3.5e9, 3.5)[0]
    assert 46.0 - geo.path_loss_db(r, 3.5e9, 3.5) == pytest.approx(-100.0)
