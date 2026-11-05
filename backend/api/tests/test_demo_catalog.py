from pathlib import Path

from app.schemas.catalog import CatalogBundle
from app.services.catalog_service import validate_catalog

DEMO = Path(__file__).resolve().parents[1] / "fixtures" / "demo_catalog.json"


def test_demo_catalog_passes_import_rules_and_stays_fictional():
    bundle = CatalogBundle.model_validate_json(DEMO.read_text(encoding="utf-8"))
    validate_catalog(bundle)
    assert bundle.products
    assert {p.brand for p in bundle.products} == {"VISHUE Demo"}
    assert all("demo" in p.tags for p in bundle.products)
    assert not bundle.stores
