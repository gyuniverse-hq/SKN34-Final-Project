from sqlalchemy import case, func, literal, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import ProductRow
from app.models.raw_oliveyoung import (
    RawOyCategoryRow,
    RawOyPriceSnapshotRow,
    RawOyProductOptionRow,
    RawOyProductRow,
)
from app.schemas.catalog_options import (
    CollectedOptionPrice,
    OptionCandidate,
    OptionCategory,
    OptionPrice,
    OptionSearchRequest,
)


def _category(row: RawOyCategoryRow) -> OptionCategory:
    return OptionCategory(
        category_id=row.category_no,
        parent_id=row.parent_category_no,
        name=row.category_name,
        path=row.category_path,
        depth=row.depth,
    )


def _price(value: int | None) -> int | None:
    return value if value is not None and value > 0 else None


def _snapshot(row: RawOyPriceSnapshotRow, source_url: str | None) -> CollectedOptionPrice:
    stock = (
        "sold_out"
        if row.is_sold_out is True
        else "in_stock"
        if row.is_sold_out is False
        else "unknown"
    )
    return CollectedOptionPrice(
        evidence_id=f"oy-price-snapshot:{row.snapshot_id}",
        source_url=source_url,
        sale_price_krw=_price(row.sale_price),
        list_price_krw=_price(row.list_price),
        collected_at_raw=row.collected_at.isoformat() if row.collected_at else None,
        stock_status=stock,
    )


class CatalogOptionRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def categories(self) -> list[OptionCategory]:
        rows = await self._session.scalars(
            select(RawOyCategoryRow).order_by(RawOyCategoryRow.category_no)
        )
        return [_category(row) for row in rows]

    async def start_search(self, category_id: str) -> OptionCategory | None:
        # All catalog and ingredient reads for this request share one read-only snapshot.
        await self._session.execute(
            text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        )
        row = await self._session.get(RawOyCategoryRow, category_id)
        return _category(row) if row else None

    async def options(self, request: OptionSearchRequest) -> tuple[int, list[OptionCandidate]]:
        tree = (
            select(RawOyCategoryRow.category_no)
            .where(RawOyCategoryRow.category_no == request.category_id)
            .cte("category_tree", recursive=True)
        )
        tree = tree.union(
            select(RawOyCategoryRow.category_no).join(
                tree, RawOyCategoryRow.parent_category_no == tree.c.category_no
            )
        )
        # The serving product and source option both have to resolve to this goods number.
        base = (
            select(
                ProductRow.id,
                ProductRow.name_ko,
                ProductRow.category,
                ProductRow.price_krw,
                RawOyCategoryRow,
                RawOyProductRow.product_url,
                RawOyProductOptionRow.option_id,
                RawOyProductOptionRow.option_name,
            )
            .select_from(RawOyProductRow)
            .join(
                ProductRow, ProductRow.id == literal("oy-") + func.lower(RawOyProductRow.goods_no)
            )
            .join(RawOyCategoryRow, RawOyProductRow.category_no == RawOyCategoryRow.category_no)
            .join(RawOyProductOptionRow, RawOyProductRow.goods_no == RawOyProductOptionRow.goods_no)
            .where(
                RawOyProductRow.category_no.in_(select(tree.c.category_no)),
                RawOyProductRow.delisted_at.is_(None),
                RawOyProductOptionRow.delisted_at.is_(None),
            )
        )
        if request.product_id is not None:
            base = base.where(ProductRow.id == request.product_id)
        if request.option_id is not None:
            base = base.where(RawOyProductOptionRow.option_id == request.option_id)

        count_query = base.with_only_columns(RawOyProductOptionRow.option_id)
        total = await self._session.scalar(select(func.count()).select_from(count_query.subquery()))
        assert total is not None
        if request.offset >= total:
            return total, []

        price = RawOyPriceSnapshotRow
        page = base.add_columns(price).outerjoin(
            price, (price.option_id == RawOyProductOptionRow.option_id) & price.is_latest.is_(True)
        )
        if request.max_price_krw is not None and request.price_basis == "collected_sale":
            page = page.order_by(
                case((price.collected_at.is_not(None) & (price.sale_price > 0), price.sale_price))
                .asc()
                .nulls_last()
            )
        page = page.order_by(ProductRow.position, ProductRow.id, RawOyProductOptionRow.option_id)
        rows = await self._session.execute(page.offset(request.offset).limit(request.limit))
        candidates = []
        for row in rows:
            product_id, name, group, reference, category, url, option_id, option_name, snapshot = (
                row
            )
            candidates.append(
                OptionCandidate(
                    product_id=product_id,
                    product_name=name,
                    catalog_category=group,
                    category=_category(category),
                    option_id=option_id,
                    option_name=option_name,
                    price=OptionPrice(
                        reference_price_krw=_price(reference),
                        collected=_snapshot(snapshot, url) if snapshot else None,
                    ),
                )
            )
        return total, candidates
