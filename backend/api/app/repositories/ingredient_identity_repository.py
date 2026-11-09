"""Read-only canonical identity lookup; never infers product/option ownership."""

import re
import unicodedata

from pydantic import ValidationError
from sqlalchemy import Text, any_, func, literal_column, or_, select
from sqlalchemy.dialects.postgresql import ARRAY, array
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.oy_mfds_ingredient_map import OyMfdsIngredientMapRow as Link
from app.models.raw_mfds_ingredient import RawMfdsIngredientRow as Mfds
from app.models.raw_oliveyoung import RawOyIngredientRow as Oy
from app.schemas.ingredient import IngredientIdentity

QUERY_RULE = "mfds-query-v1"
AMOUNT_SUFFIX = re.compile(r"\s*\(\s*\d+(?:,\d{3})*(?:\.\d+)?\s*(?:ppm|ppb|%|iu)\s*\)\s*$", re.I)


OFFICIAL_SYNONYM_SEPARATOR = r"\s*\^\s*"


def _name(value):
    return " ".join(unicodedata.normalize("NFKC", value or "").split())


def _official_synonyms(value: str | None) -> set[str]:
    """MFDS synonym_raw uses caret separators; commas can be part of chemical names."""
    return {normalized for alias in (value or "").split("^") if (normalized := _name(alias))}


def _current_link(row):
    method, original = row[4], _name(row[8])
    if method in {"amount_suffix_exact", "amount_suffix_synonym"}:
        amount = AMOUNT_SUFFIX.search(original)
        if amount is None:
            return False
        original = original[: amount.start()].strip()
    if method in {"exact_name", "amount_suffix_exact"}:
        return bool(original) and original == _name(row[1])
    if method in {"official_synonym", "amount_suffix_synonym"}:
        aliases = _official_synonyms(row[10])
        return bool(original) and original in aliases
    # Manual rows currently have no reviewed dictionary hash: never reissue them
    # as verified identities for a possibly changed snapshot.
    return False


def _link_name(row):
    value = _name(row[8])
    if row[4] in {"amount_suffix_exact", "amount_suffix_synonym"}:
        value = AMOUNT_SUFFIX.sub("", value).strip()
    return value.lower()


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
            labels = [standard[1], standard[2], *_official_synonyms(standard[3])]
            for label in labels:
                key = _name(label).lower()
                if key in identities:
                    identities[key].add(standard[0])
        return {
            row[3]: identity
            for row, identity in candidates
            if identities[_link_name(row)] == {identity.mfds_ingredient_id}
        }

    async def resolve(self, name: str) -> IngredientIdentity | None:
        target = " ".join(unicodedata.normalize("NFKC", name).lower().split())
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
        if len({row[0] for row in rows}) != 1:
            return None
        if not any(row[13] for row in rows):
            # An OY-only alias (including an amount suffix) needs the same current
            # base-name uniqueness check used for product entries.
            links = await self.for_entries([row[3] for row in rows if row[3] is not None])
            resolved = {identity.mfds_ingredient_id: identity for identity in links.values()}
            return next(iter(resolved.values())) if len(resolved) == 1 else None
        candidates = {}
        for row in rows:
            method = (
                "standard_name"
                if row[11]
                else "english_name"
                if row[12]
                else "official_synonym"
                if row[13]
                else None
            )
            if (identity := _identity(row, method)) is not None:
                candidates[identity.mfds_ingredient_id] = identity
        return next(iter(candidates.values())) if len(candidates) == 1 else None
