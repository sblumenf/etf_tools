import pytest
from etf_pipeline.xray.calculations import compute_hhi, compute_top_n_weight


def test_compute_hhi_empty():
    assert compute_hhi([]) == 0.0


def test_compute_hhi_single_holding():
    assert compute_hhi([100.0]) == 10000.0


def test_compute_hhi_equal_weight():
    # 4 equal weights of 25 each: 4 * (25^2) = 2500
    assert compute_hhi([25.0, 25.0, 25.0, 25.0]) == pytest.approx(2500.0)


def test_compute_hhi_known_value():
    # [50, 50] -> 50^2 + 50^2 = 5000
    assert compute_hhi([50.0, 50.0]) == pytest.approx(5000.0)


def test_compute_top_n_weight_n_greater_than_length():
    # n > len(weights) should return sum of all weights
    weights = [30.0, 20.0, 10.0]
    assert compute_top_n_weight(weights, 10) == pytest.approx(60.0)


def test_compute_top_n_weight_n5_on_10_items():
    weights = [20.0, 15.0, 12.0, 10.0, 8.0, 7.0, 6.0, 5.0, 4.0, 3.0]
    # top 5: 20 + 15 + 12 + 10 + 8 = 65
    assert compute_top_n_weight(weights, 5) == pytest.approx(65.0)
