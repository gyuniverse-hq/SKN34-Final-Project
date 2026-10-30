from sqlalchemy import Text, cast, delete, select, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LookItemRow, LookRow, ProductRow, ShadeRow, StoreRow
from app.schemas.catalog import CatalogBundle, CelebLook, LookItem, Product, Shade, Store


def build_search_text(product: Product) -> str:
    parts = [
        product.brand,
        product.name,
        product.name_ko,
        product.description,
        *product.tags,
        *(s.name for s in product.shades),
    ]
    return " ".join(parts).lower()


def _product(row: ProductRow) -> Product:
    return Product(
        id=row.id,
        brand=row.brand,
        name=row.name,
        name_ko=row.name_ko,
        category=row.category,
        makeup_zone=row.makeup_zone,
        texture=row.texture,
        price_krw=row.price_krw,
        volume=row.volume,
        shades=[Shade(id=s.id, name=s.name, hex=s.hex) for s in row.shades],
        description=row.description,
        key_ingredients=row.key_ingredients,
        tags=row.tags,
        image_url=row.image_url,
        search_keyword=row.search_keyword,
    )


def _look(row: LookRow) -> CelebLook:
    return CelebLook(
        id=row.id,
        title=row.title,
        inspiration=row.inspiration,
        description=row.description,
        thumbnail_url=row.thumbnail_url,
        tutorial_query=row.tutorial_query,
        items=[
            LookItem(product_id=i.product_id, shade_id=i.shade_id, step=i.step) for i in row.items
        ],
        makeup=row.makeup,
        tags=row.tags,
    )


def _store(row: StoreRow) -> Store:
    return Store(
        id=row.id,
        name=row.name,
        address=row.address,
        district=row.district,
        lat=row.lat,
        lng=row.lng,
        hours=row.hours,
        phone=row.phone,
        pickup_available=row.pickup_available,
    )


class CatalogRepository:
    """PostgreSQL access for products, looks and stores. Returns API schemas, never ORM rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search_products(
        self,
        terms: list[str],
        category: str | None = None,
        ids: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> list[Product]:
        """`tags` matches products carrying any of them; an empty list matches nothing."""
        stmt = select(ProductRow).order_by(ProductRow.position, ProductRow.id)
        if ids is not None:
            stmt = stmt.where(ProductRow.id.in_(ids))
        if category:
            stmt = stmt.where(ProductRow.category == category)
        if tags is not None:
            stmt = stmt.where(ProductRow.tags.has_any(cast(tags, ARRAY(Text))))
        for term in terms:
            stmt = stmt.where(ProductRow.search_text.contains(term.lower(), autoescape=True))
        rows = (await self._session.scalars(stmt)).all()
        return [_product(r) for r in rows]

    async def get_product(self, product_id: str) -> Product | None:
        row = await self._session.get(ProductRow, product_id)
        return _product(row) if row else None

    async def list_looks(self) -> list[CelebLook]:
        stmt = select(LookRow).order_by(LookRow.position, LookRow.id)
        return [_look(r) for r in (await self._session.scalars(stmt)).all()]

    async def get_look(self, look_id: str) -> CelebLook | None:
        row = await self._session.get(LookRow, look_id)
        return _look(row) if row else None

    async def list_stores(self) -> list[Store]:
        stmt = select(StoreRow).order_by(StoreRow.position, StoreRow.id)
        return [_store(r) for r in (await self._session.scalars(stmt)).all()]

    async def replace_catalog(self, bundle: CatalogBundle) -> None:
        """Replaces the whole catalog in one transaction (seed/import)."""
        async with self._session.begin():
            for table in (LookItemRow, LookRow, ShadeRow, ProductRow, StoreRow):
                await self._session.execute(delete(table))
            for pos, p in enumerate(bundle.products):
                self._session.add(
                    ProductRow(
                        id=p.id,
                        position=pos,
                        brand=p.brand,
                        name=p.name,
                        name_ko=p.name_ko,
                        category=p.category,
                        makeup_zone=p.makeup_zone,
                        texture=p.texture,
                        price_krw=p.price_krw,
                        volume=p.volume,
                        description=p.description,
                        key_ingredients=p.key_ingredients,
                        tags=p.tags,
                        image_url=p.image_url,
                        search_keyword=p.search_keyword,
                        search_text=build_search_text(p),
                        shades=[
                            ShadeRow(id=s.id, position=i, name=s.name, hex=s.hex)
                            for i, s in enumerate(p.shades)
                        ],
                    )
                )
            await self._session.flush()
            for pos, look in enumerate(bundle.looks):
                self._session.add(
                    LookRow(
                        id=look.id,
                        position=pos,
                        title=look.title,
                        inspiration=look.inspiration,
                        description=look.description,
                        thumbnail_url=look.thumbnail_url,
                        tutorial_query=look.tutorial_query,
                        makeup=look.makeup.model_dump(mode="json", by_alias=True),
                        tags=look.tags,
                        items=[
                            LookItemRow(
                                position=i,
                                product_id=it.product_id,
                                shade_id=it.shade_id,
                                step=it.step,
                            )
                            for i, it in enumerate(look.items)
                        ],
                    )
                )
            for pos, s in enumerate(bundle.stores):
                self._session.add(
                    StoreRow(
                        id=s.id,
                        position=pos,
                        name=s.name,
                        address=s.address,
                        district=s.district,
                        lat=s.lat,
                        lng=s.lng,
                        hours=s.hours,
                        phone=s.phone,
                        pickup_available=s.pickup_available,
                    )
                )
            await self._session.flush()
            await self._session.execute(
                text(
                    """
                    UPDATE raw_oy_product AS raw
                    SET is_in_catalog = EXISTS (
                        SELECT 1 FROM products AS product
                        WHERE product.id = 'oy-' || lower(raw.goods_no)
                    )
                    """
                )
            )
