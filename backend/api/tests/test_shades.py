from app.schemas.shade import SkinTone
from app.services.shade_service import MST_ITA, MST_LAB, estimate_skin_lab


def test_mst_level_maps_to_reference_swatch():
    assert estimate_skin_lab(SkinTone(mst=5)) == MST_LAB[4]


def test_swatch_ita_decreases_with_level():
    assert list(MST_ITA) == sorted(MST_ITA, reverse=True)


def test_higher_ita_means_lighter_skin():
    light = estimate_skin_lab(SkinTone(mst=4, ita=75))
    dark = estimate_skin_lab(SkinTone(mst=4, ita=40))
    assert light[0] > MST_LAB[3][0] > dark[0]


def test_ita_never_moves_past_halfway_to_a_neighbor_level():
    extreme = estimate_skin_lab(SkinTone(mst=4, ita=90))
    halfway = (MST_LAB[3][0] + MST_LAB[2][0]) / 2
    assert extreme[0] == halfway


def test_undertone_shifts_yellowness():
    warm = estimate_skin_lab(SkinTone(mst=4, undertone="warm"))
    cool = estimate_skin_lab(SkinTone(mst=4, undertone="cool"))
    assert warm[2] > cool[2]


def test_recommend_ranks_only_base_shades_by_delta_e(client):
    res = client.post("/api/shades/recommend", json={"skin": {"mst": 2, "ita": 50}, "limit": 3})
    assert res.status_code == 200
    body = res.json()
    assert body["skinHex"].startswith("#")
    matches = body["matches"]
    assert len(matches) == 3
    assert {m["productId"] for m in matches} <= {"base-1", "base-2"}
    assert [m["deltaE"] for m in matches] == sorted(m["deltaE"] for m in matches)
    assert matches[0]["shadeId"] in {"13", "21"}


def test_recommend_validates_skin_tone(client):
    res = client.post("/api/shades/recommend", json={"skin": {"mst": 11}})
    assert res.status_code == 400
    assert res.json() == {"error": "Invalid request", "code": "invalid_request"}
