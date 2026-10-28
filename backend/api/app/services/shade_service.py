from math import atan2, degrees

from fastapi import Depends

from app.core.errors import ApiError
from app.schemas.shade import (
    ShadeMatch,
    ShadeRecommendRequest,
    ShadeRecommendResponse,
    SimilarReason,
    SimilarShadeMatch,
    SimilarShadesResponse,
    SimilarSource,
    SkinTone,
)
from app.services.catalog_service import CatalogService, get_catalog_service
from app.services.color import Lab, ciede2000, hex_to_lab, lab_to_hex

# CIEDE2000 below this reads as "very close" for cosmetic swatches (noticeable at a glance ~5).
CLOSE_COLOR_DELTA_E = 5.0

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

    async def similar(self, product_id: str, shade_id: str, limit: int) -> SimilarShadesResponse:
        """Shades for the same makeup zone, closest official color first. The source is excluded."""
        product = await self._catalog.get_product(product_id)
        if product is None:
            raise ApiError(404, "Product not found", "not_found")
        shade = next((s for s in product.shades if s.id == shade_id), None)
        if shade is None:
            raise ApiError(404, "Shade not found", "shade_not_found")
        if product.makeup_zone is None:
            raise ApiError(400, "Product cannot be tried on", "not_try_on")

        source_lab = hex_to_lab(shade.hex)
        candidates = [
            p
            for p in await self._catalog.list_products(with_images=False)
            if p.makeup_zone == product.makeup_zone
        ]
        matches: list[SimilarShadeMatch] = []
        for p in candidates:
            for s in p.shades:
                if p.id == product.id and s.id == shade.id:
                    continue
                delta_e = round(ciede2000(source_lab, hex_to_lab(s.hex)), 2)
                reasons: list[SimilarReason] = []
                if delta_e <= CLOSE_COLOR_DELTA_E:
                    reasons.append("close_color")
                if p.texture == product.texture:
                    reasons.append("same_texture")
                if p.category == product.category:
                    reasons.append("same_category")
                matches.append(
                    SimilarShadeMatch(
                        product_id=p.id, shade_id=s.id, delta_e=delta_e, reasons=reasons
                    )
                )
        matches.sort(key=lambda m: (m.delta_e, m.product_id, m.shade_id))
        matches = matches[:limit]
        ids = list(dict.fromkeys(m.product_id for m in matches))
        products = await self._catalog.list_products(ids=ids) if ids else []
        return SimilarShadesResponse(
            source=SimilarSource(
                product_id=product.id,
                shade_id=shade.id,
                hex=shade.hex,
                makeup_zone=product.makeup_zone,
            ),
            matches=matches,
            products=products,
        )


def get_shade_service(catalog: CatalogService = Depends(get_catalog_service)) -> ShadeService:
    return ShadeService(catalog)
