"""compare_b0 pair verdict helper (no weights / images)."""
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))


def test_winner_rule():
    before = np.array([1.0, 2.0, 3.0])
    after = np.array([1.5, 1.0, 3.0])
    winners = []
    for b, a in zip(before, after):
        d = a - b
        winners.append("after" if d > 1e-4 else "before" if d < -1e-4 else "tie")
    assert winners == ["after", "before", "tie"]


def test_pool_sanity_exports_exist():
    from learn_astra import OUT

    summary = OUT / "pool_sanity_b0" / "summary.json"
    assert summary.exists()
    data = __import__("json").loads(summary.read_text(encoding="utf8"))
    assert data["n"] >= 100
    assert data["after_win_rate"] > 0.7
