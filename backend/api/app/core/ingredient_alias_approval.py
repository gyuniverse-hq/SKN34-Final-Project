"""Source-grounded MFDS synonym policy shared by API identity checks.

Single verbatim dictionary aliases are source-backed. Split aliases require a
reviewed, hash-bound approval. Ambiguity is checked separately against the DB.
"""

import csv
import re
import unicodedata
from datetime import date
from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings

OFFICIAL_SYNONYM_SEPARATOR = r"\s*(?:\^|(?<![0-9A-Za-z]),|,(?![0-9A-Za-z])|,(?=[A-Za-z]{2,}))\s*"
AMOUNT_SUFFIX = re.compile(r"\s*\(\s*\d+(?:,\d{3})*(?:\.\d+)?\s*(?:ppm|ppb|%|iu)\s*\)\s*$", re.I)
APPROVAL_COLUMNS = (
    "mfds_ingredient_id",
    "candidate_alias",
    "source_hash",
    "reviewed_by",
    "reviewed_at",
)
SOURCE_HASH = re.compile(r"^[0-9a-f]{64}$")
ApprovalKey = tuple[int, str, str]


def normalize_name(value: str | None) -> str:
    return " ".join(unicodedata.normalize("NFKC", value or "").split())


class IngredientApprovalError(ValueError):
    """A configured approval CSV cannot be used."""


def official_name_keys(name_ko: str | None, name_en: str | None) -> set[str]:
    return {key for name in (name_ko, name_en) if (key := normalize_name(name).lower())}


def dictionary_name_keys(
    name_ko: str | None, name_en: str | None, synonym_raw: str | None
) -> set[str]:
    return official_name_keys(name_ko, name_en) | {
        alias.lower() for alias in official_synonyms(synonym_raw)
    }


def without_trailing_amount(value: str) -> str | None:
    """Drop one final parenthesized concentration with a supported unit."""
    normalized = normalize_name(value)
    amount = AMOUNT_SUFFIX.search(normalized)
    return (normalized[: amount.start()].strip() or None) if amount else None


def official_synonyms(value: str | None) -> set[str]:
    return {
        alias
        for part in re.split(OFFICIAL_SYNONYM_SEPARATOR, normalize_name(value))
        if (alias := normalize_name(part))
    }


def source_single_alias(value: str | None, alias: str) -> bool:
    """Only an unsplit original MFDS value is trusted without manual approval."""
    tokens = official_synonyms(value)
    return len(tokens) == 1 and normalize_name(value).lower() == normalize_name(alias).lower()


def read_approval_records(path: Path) -> dict[ApprovalKey, tuple[str, str]]:
    """Read a single validated snapshot, including the review metadata."""
    approved: dict[ApprovalKey, tuple[str, str]] = {}
    try:
        with path.open(encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file, strict=True)
            if tuple(reader.fieldnames or ()) != APPROVAL_COLUMNS:
                raise IngredientApprovalError("Invalid MFDS approval columns")
            for line, record in enumerate(reader, 2):
                try:
                    mfds_id = int(record["mfds_ingredient_id"])
                    alias = normalize_name(record["candidate_alias"]).lower()
                    digest = record["source_hash"] or ""
                    reviewer = (record["reviewed_by"] or "").strip()
                    reviewed = (record["reviewed_at"] or "").strip()
                    date.fromisoformat(reviewed)
                except (TypeError, ValueError) as exc:
                    raise IngredientApprovalError(f"Invalid MFDS approval at row {line}") from exc
                key = (mfds_id, alias, digest)
                if (
                    None in record
                    or mfds_id <= 0
                    or not alias
                    or not SOURCE_HASH.fullmatch(digest)
                    or not reviewer
                    or key in approved
                ):
                    raise IngredientApprovalError(f"Unverified or duplicate approval at row {line}")
                approved[key] = (reviewer, reviewed)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise IngredientApprovalError("Cannot read the MFDS approval CSV") from exc
    return approved


@lru_cache(maxsize=16)
def load_approved_aliases(path: str | None) -> frozenset[ApprovalKey]:
    """Read a versioned approval CSV once per process (restart to reload)."""
    if not path:
        return frozenset()
    source = Path(path)
    if not source.is_absolute():
        raise IngredientApprovalError("INGREDIENT_ALIAS_APPROVALS_PATH must be absolute")
    return frozenset(read_approval_records(source))


def get_ingredient_alias_approvals() -> frozenset[ApprovalKey]:
    return load_approved_aliases(get_settings().ingredient_alias_approvals_path)


def approved_synonym(
    raw: str | None,
    alias: str,
    mfds_id: int,
    source_hash: str,
    approved: frozenset[ApprovalKey],
) -> bool:
    name = normalize_name(alias).lower()
    if not name or name not in {part.lower() for part in official_synonyms(raw)}:
        return False
    return source_single_alias(raw, alias) or (mfds_id, name, source_hash) in approved
