def compute_hhi(weights: list[float]) -> float:
    """Compute HHI from list of percentage weights (0-100 scale)."""
    return sum(w ** 2 for w in weights)


def compute_top_n_weight(weights_sorted_desc: list[float], n: int) -> float:
    return sum(weights_sorted_desc[:n])
