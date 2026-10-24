from math import atan2, degrees

from fastapi import Depends

from app.schemas.shade import ShadeMatch, ShadeRecommendRequest, ShadeRecommendResponse, SkinTone
from app.services.catalog_service import CatalogService, get_catalog_service
from app.services.color import Lab, ciede2000, hex_to_lab, lab_to_hex

# Monk Skin Tone scale reference swatches (Google, CC BY 4.0), level 1..10.
MST_HEX = (
    "#f6ede4", "#f3e7db", "#f7ead0", "#eadaba", "#d7bd96",
    "#a07e56", "#825c43", "#604134", "#3a312a", "#292420",
)  # fmt: skip
MST_LAB: tuple[Lab, ...] = tuple(hex_to_lab(h) for h in MST_HEX)
# ITA° = atan((L* - 50) / b*); decreases monotonically from MST 1 to 10.
MST_ITA: tuple[float, ...] = tuple(degrees(atan2(lab[0] - 50, lab[2])) for lab in MST_LAB)

# The MST level is the primary signal; ITA may move the estimate at most halfway to a neighbor.
MAX_ITA_BLEND = 0.5

# (Δa*, Δb*) heuristic shift: cool skin reads pinker/less yellow, warm skin more yellow.
UNDERTONE_SHIFT = {"cool": (1.0, -3.0), "neutral": (0.0, 0.0), "warm": (-0.5, 3.0)}


def estimate_skin_lab(skin: SkinTone) -> Lab:
    i = skin.mst - 1
    lab = MST_LAB[i]
    if skin.ita is not None:
        j = i - 1 if skin.ita > MST_ITA[i] else i + 1
        if 0 <= j < len(MST_LAB):
            t = (skin.ita - MST_ITA[i]) / (MST_ITA[j] - MST_ITA[i])
            t = min(max(t, 0.0), MAX_ITA_BLEND)
            lab = (
                lab[0] + (MST_LAB[j][0] - lab[0]) * t,
                lab[1] + (MST_LAB[j][1] - lab[1]) * t,
                lab[2] + (MST_LAB[j][2] - lab[2]) * t,
            )
    da, db = UNDERTONE_SHIFT[skin.undertone]
    return (lab[0], lab[1] + da, lab[2] + db)


class ShadeService:
    """Ranks base-makeup shades by CIEDE2000 distance from the on-device skin tone estimate."""

    def __init__(self, catalog: CatalogService) -> None:
        self._catalog = catalog

    async def recommend(self, req: ShadeRecommendRequest) -> ShadeRecommendResponse:
        skin = estimate_skin_lab(req.skin)
        matches = [
            ShadeMatch(
                product_id=p.id,
                shade_id=s.id,
                brand=p.brand,
                product_name=p.name,
                shade_name=s.name,
                hex=s.hex,
                delta_e=round(ciede2000(skin, hex_to_lab(s.hex)), 2),
            )
            for p in await self._catalog.list_products(category="base", with_images=False)
            for s in p.shades
        ]
        matches.sort(key=lambda m: m.delta_e)
        return ShadeRecommendResponse(skin_hex=lab_to_hex(skin), matches=matches[: req.limit])


def get_shade_service(catalog: CatalogService = Depends(get_catalog_service)) -> ShadeService:
    return ShadeService(catalog)
