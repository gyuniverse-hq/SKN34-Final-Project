"""compare_score helpers that do not need torch weights."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))


def test_summary_path_names():
    from compare_score import _summary_path

    assert _summary_path("resnet18").name == "fit_summary.json"
    assert _summary_path("dinov2_vits14").name == "fit_summary_dinov2_vits14.json"


def test_dinov2_fit_summary_has_alpha():
    from learn_astra import OUT

    path = OUT / "fit_summary_dinov2_vits14.json"
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf8"))
    assert data["targets"]["total"]["alpha"] > 0
