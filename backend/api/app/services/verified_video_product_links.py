"""Expose confirmed research matches on the existing video product responses."""

from collections import defaultdict

from app.repositories.verified_video_product_repository import VerifiedVideoProductLink
from app.schemas.celebrity_video import CelebrityVideo
from app.schemas.style_look import StyleLook


def attach_verified_links(
    videos: list[CelebrityVideo] | list[StyleLook],
    links: list[VerifiedVideoProductLink],
    source: str,
) -> list[CelebrityVideo] | list[StyleLook]:
    by_mention: dict[tuple[str, int], list[VerifiedVideoProductLink]] = defaultdict(list)
    for link in links:
        if link.source == source:
            by_mention[(link.video_id, link.mention_number)].append(link)

    result = []
    for video in videos:
        products = []
        for product in video.products:
            candidates = by_mention.get((video.id, product.number), [])
            if product.mapping_verified is True:
                products.append(product)
                continue
            if len(candidates) > 1 and all(link.link_type == "split" for link in candidates):
                for link in sorted(candidates, key=lambda item: item.product_id):
                    update = {
                        "mapping_verified": True,
                        "catalog_product_id": link.product_id,
                        "catalog_shade_id": link.shade_id,
                    }
                    if link.display_brand:
                        update["brand"] = link.display_brand
                    if link.display_name:
                        update["name"] = link.display_name
                    products.append(product.model_copy(update=update))
                continue
            # Multiple unrelated candidates remain unresolved; only a curated split
            # relation is allowed to produce more than one serving product.
            if len(candidates) != 1:
                products.append(product)
                continue
            link = candidates[0]
            products.append(
                product.model_copy(
                    update={
                        "mapping_verified": True,
                        "catalog_product_id": link.product_id,
                        "catalog_shade_id": link.shade_id,
                    }
                )
            )
        result.append(video.model_copy(update={"products": products}))
    return result
