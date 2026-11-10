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

OFFICIAL_SYNONYM_SEPARATOR = r"\s*(?:\^|(?<![0-9A-Za-z]),|,(?![0-9A-Za-z])|,(?=[A-Za-z]{2,}))\s*"
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


def official_synonyms(value: str | None) -> set[str]:
    return {
        alias
        for part in re.split(OFFICIAL_SYNONYM_SEPARATOR, normalize_name(value))
        if (alias := normalize_name(part))
    }


def source_single_alias(value: str | None, alias: str) -> bool:
    """Only an unsplit original MFDS value is trusted without manual approval."""
    tokens = official_synonyms(value)
    return len(tokens) == 1 and normalize_name(value).casefold() == normalize_name(alias).casefold()


@lru_cache(maxsize=16)
def load_approved_aliases(path: str | None) -> frozenset[ApprovalKey]:
    """Read a versioned, externally reviewed CSV once per process (restart to reload)."""
    if not path:
        return frozenset()
    source = Path(path)
    if not source.is_absolute():
        raise ValueError("INGREDIENT_ALIAS_APPROVALS_PATH must be absolute")
    approved: set[ApprovalKey] = set()
    with source.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if tuple(reader.fieldnames or ()) != APPROVAL_COLUMNS:
            raise ValueError("Invalid MFDS approval columns")
        for line, record in enumerate(reader, 2):
            try:
                mfds_id = int(record["mfds_ingredient_id"])
                alias = normalize_name(record["candidate_alias"]).casefold()
                digest = record["source_hash"]
                reviewer = (record["reviewed_by"] or "").strip()
                reviewed = (record["reviewed_at"] or "").strip()
                date.fromisoformat(reviewed)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid MFDS approval at row {line}") from exc
            key = (mfds_id, alias, digest)
            if (
                mfds_id <= 0
                or not alias
                or not SOURCE_HASH.fullmatch(digest)
                or not reviewer
                or key in approved
            ):
                raise ValueError(f"Unverified or duplicate MFDS approval at row {line}")
            approved.add(key)
    return frozenset(approved)


def approved_synonym(
    raw: str | None,
    alias: str,
    mfds_id: int,
    source_hash: str,
    approved: frozenset[ApprovalKey],
) -> bool:
    name = normalize_name(alias).casefold()
    if not name or name not in {part.casefold() for part in official_synonyms(raw)}:
        return False
    return source_single_alias(raw, alias) or (mfds_id, name, source_hash) in approved
