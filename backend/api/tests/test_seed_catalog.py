from pathlib import Path

from app.schemas.catalog import CatalogBundle
from app.services.catalog_service import validate_catalog

SEED = Path(__file__).resolve().parents[1] / "seed" / "catalog.json"


def test_seed_file_matches_schema_and_integrity_rules():
    validate_catalog(CatalogBundle.model_validate_json(SEED.read_text(encoding="utf-8")))
