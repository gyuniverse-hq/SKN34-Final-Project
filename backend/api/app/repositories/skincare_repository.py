from fastapi import Depends
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.models.catalog import ProductRow
from app.models.skincare import SkincareServingRow
from app.repositories.catalog_repository import build_search_text
from app.schemas.skincare import SkincareSnapshot


class SkincareRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def read(self) -> SkincareSnapshot | None:
        row = await self.session.get(SkincareServingRow, 1)
        return SkincareSnapshot.model_validate(row.payload) if row else None

    async def publish(self, snapshot: SkincareSnapshot):
        payload = snapshot.model_dump(mode="json", by_alias=True)
        async with self.session.begin():
            for option in snapshot.options:
                product = option.product
                row = await self.session.get(ProductRow, product.id)
                if row and row.category != "skincare":
                    raise ValueError("Product ID collides with an existing non-skincare product")
                if row is None:
                    row = ProductRow(id=product.id)
                    self.session.add(row)
                for field in (
                    "brand",
                    "name",
                    "name_ko",
                    "category",
                    "makeup_zone",
                    "texture",
                    "volume",
                    "description",
                    "key_ingredients",
                    "tags",
                    "image_url",
                    "search_keyword",
                ):
                    setattr(row, field, getattr(product, field))
                row.price_krw = min(
                    o.price_krw for o in snapshot.options if o.product.id == product.id
                )
                row.search_text = build_search_text(product)
            stmt = insert(SkincareServingRow).values(
                id=1, data_version=snapshot.data_version, payload=payload
            )
            await self.session.execute(
                stmt.on_conflict_do_update(
                    index_elements=["id"],
                    set_={"data_version": snapshot.data_version, "payload": payload},
                )
            )


def get_skincare_repository(session: AsyncSession = Depends(get_session)):
    return SkincareRepository(session)
