import pytest

from app.services.color import ciede2000, hex_to_lab, lab_to_hex

# Sharma, Wu, Dalal (2005), "The CIEDE2000 Color-Difference Formula", Table 1.
SHARMA_PAIRS = [
    ((50.0000, 2.6772, -79.7751), (50.0000, 0.0000, -82.7485), 2.0425),
    ((50.0000, 0.0000, 0.0000), (50.0000, -1.0000, 2.0000), 2.3669),
    ((50.0000, 2.5000, 0.0000), (73.0000, 25.0000, -18.0000), 27.1492),
    ((60.2574, -34.0099, 36.2677), (60.4626, -34.1751, 39.4387), 1.2644),
    ((50.0000, 2.5000, 0.0000), (50.0000, 3.1736, 0.5854), 1.0000),
]


@pytest.mark.parametrize(("lab1", "lab2", "expected"), SHARMA_PAIRS)
def test_ciede2000_matches_reference_data(lab1, lab2, expected):
    assert ciede2000(lab1, lab2) == pytest.approx(expected, abs=1e-4)
    assert ciede2000(lab2, lab1) == pytest.approx(expected, abs=1e-4)


def test_white_and_black():
    assert hex_to_lab("#ffffff") == pytest.approx((100, 0, 0), abs=0.01)
    assert hex_to_lab("#000000") == pytest.approx((0, 0, 0), abs=0.01)


@pytest.mark.parametrize("color", ["#f6ede4", "#a07e56", "#292420", "#c0485a"])
def test_hex_lab_round_trip(color):
    assert lab_to_hex(hex_to_lab(color)) == color
