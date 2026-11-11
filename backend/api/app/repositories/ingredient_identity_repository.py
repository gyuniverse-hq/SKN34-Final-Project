"""Read-only canonical identity lookup; never infers product/option ownership."""

from pydantic import ValidationError
from sqlalchemy import Text, any_, func, literal_column, or_, select
from sqlalchemy.dialects.postgresql import ARRAY, array
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ingredient_alias_approval import (
    OFFICIAL_SYNONYM_SEPARATOR,
    approved_synonym,
    dictionary_name_keys,
    get_ingredient_alias_approvals,
    official_name_keys,
    official_synonyms,
    without_trailing_amount,
)
from app.core.ingredient_alias_approval import (
    normalize_name as _name,
)
from app.models.oy_mfds_ingredient_map import OyMfdsIngredientMapRow as Link
from app.models.raw_mfds_ingredient import RawMfdsIngredientRow as Mfds
from app.models.raw_oliveyoung import RawOyIngredientRow as Oy
from app.schemas.ingredient import IngredientIdentity

QUERY_RULE = "mfds-query-v1"


def _official_synonyms(value: str | None) -> set[str]:
    """Retain the compatibility import for the reviewed split-alias parser."""
    return official_synonyms(value)


def _approvals():
    return get_ingredient_alias_approvals()


def _link_name(row):
    value = _name(row[8])
    if row[4] in {"amount_suffix_exact", "amount_suffix_synonym"}:
        value = without_trailing_amount(value) or ""
    return value.lower()


def _current_link(row):
    method, original = row[4], _link_name(row)
    if method in {"exact_name", "amount_suffix_exact"}:
        return original in official_name_keys(row[1], row[9])
    if method in {"official_synonym", "amount_suffix_synonym"}:
        return bool(original) and approved_synonym(row[10], original, row[0], row[2], _approvals())
    # Manual rows lack a reviewed dictionary hash and cannot prove current identity.
    return False


def _key(column):
    return func.lower(
        func.trim(
            func.regexp_replace(func.normalize(column, literal_column("NFKC")), r"\s+", " ", "g")
        )
    )


def _identity(row, method=None):
    if method is None and not _current_link(row):
        return None
    try:
        return IngredientIdentity(
            mfds_ingredient_id=row[0],
            name_ko=row[1],
            source_hash=row[2],
            match_method=method or row[4],
            rule_version=QUERY_RULE if method else row[5],
            reviewed_by=None if method else row[6],
            reviewed_at=None if method else row[7],
        )
    except ValidationError:
        return None


class IngredientIdentityRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    def _select(self):
        return (
            select(
                Mfds.ingredient_id,
                Mfds.name_ko,
                Mfds.source_hash,
                Oy.ingredient_id,
                Link.match_method,
                Link.rule_version,
                Link.reviewed_by,
                Link.reviewed_at,
                Oy.ingredient_name,
                Mfds.name_en,
                Mfds.synonym_raw,
            )
            .select_from(Mfds)
            .outerjoin(Link, Link.mfds_ingredient_id == Mfds.ingredient_id)
            .outerjoin(Oy, Oy.ingredient_id == Link.oy_ingredient_id)
            .where(Mfds.is_current.is_(True))
        )

    async def for_entries(self, ids: list[int]) -> dict[int, IngredientIdentity]:
        if not ids:
            return {}
        rows = (
            await self._session.execute(
                self._select().where(Oy.ingredient_id.in_(ids)).execution_options(autoflush=False)
            )
        ).all()
        candidates = [(row, identity) for row in rows if (identity := _identity(row)) is not None]
        if not candidates:
            return {}
        names = list({_link_name(row) for row, _ in candidates})
        # Recheck uniqueness too: a dictionary refresh may add a competing synonym.
        standards = (
            await self._session.execute(
                select(Mfds.ingredient_id, Mfds.name_ko, Mfds.name_en, Mfds.synonym_raw)
                .where(
                    Mfds.is_current.is_(True),
                    or_(
                        _key(Mfds.name_ko).in_(names),
                        _key(Mfds.name_en).in_(names),
                        func.regexp_split_to_array(
                            _key(Mfds.synonym_raw), OFFICIAL_SYNONYM_SEPARATOR
                        ).op("&&")(array(names).cast(ARRAY(Text))),
                    ),
                )
                .execution_options(autoflush=False)
            )
        ).all()
        identities = {name: set() for name in names}
        for standard in standards:
            for key in dictionary_name_keys(standard[1], standard[2], standard[3]):
                if key in identities:
                    identities[key].add(standard[0])
        return {
            row[3]: identity
            for row, identity in candidates
            if identities[_link_name(row)] == {identity.mfds_ingredient_id}
        }

    async def resolve(self, name: str) -> IngredientIdentity | None:
        target = _name(name).lower()
        official = or_(
            _key(Mfds.name_ko) == target,
            _key(Mfds.name_en) == target,
            target
            == any_(func.regexp_split_to_array(_key(Mfds.synonym_raw), OFFICIAL_SYNONYM_SEPARATOR)),
        )
        rows = (
            await self._session.execute(
                self._select()
                .add_columns(
                    (_key(Mfds.name_ko) == target).label("standard"),
                    (_key(Mfds.name_en) == target).label("english"),
                    official.label("official"),
                )
                .where(or_(official, _key(Oy.ingredient_name) == target))
                .execution_options(autoflush=False)
            )
        ).all()
        # An explicit official name can identify the sole official owner. Raw
        # product links still require uniqueness across all dictionary names.
        official_names = [row for row in rows if row[11] or row[12]]
        if official_names:
            if len({row[0] for row in official_names}) != 1:
                return None
            row = official_names[0]
            return _identity(row, "standard_name" if row[11] else "english_name")

        aliases = [row for row in rows if row[13]]
        if aliases:
            # Unapproved aliases still count as competitors and never fall back to OY.
            if len({row[0] for row in aliases}) != 1:
                return None
            row = aliases[0]
            if approved_synonym(row[10], target, row[0], row[2], _approvals()):
                return _identity(row, "official_synonym")
            return None

        # OY-only names (including amount suffixes) use the product-link policy.
        ids = [row[3] for row in rows if row[3] is not None and _name(row[8]).lower() == target]
        links = await self.for_entries(ids)
        resolved = {identity.mfds_ingredient_id: identity for identity in links.values()}
        return next(iter(resolved.values())) if len(resolved) == 1 else None
