"""SYNTHETIC fixtures only: fake SQL sessions, real Repository/Service/HTTP handlers."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.repositories.ingredient_repository import (
    IngredientRepository,
    catalog_fingerprint,
    fingerprint,
)
from app.schemas.ingredient import IngredientMapping
from app.services.ingredient_service import IngredientService, get_ingredient_service


class Rows:
    def __init__(self, value):
        self.value = value

    def all(self):
        return self.value


class Session:
    def __init__(self, pages):
        self.pages, self.statements = list(pages), []

    async def execute(self, stmt):
        assert stmt.is_select and stmt.get_execution_options()["autoflush"] is False
        self.statements.append(stmt)
        value = self.pages.pop(0)
        if isinstance(value, Exception):
            raise value
        assert all(len(row) == len(stmt.selected_columns) for row in value)
        return Rows(value)


@pytest.fixture
def data():
    time = datetime(2026, 11, 2, tzinfo=UTC)
    product = ("oy-fixture", "lip", "matte")
    shades = [("01", "First", "#112233"), ("01-2", "Second", "#445566")]
    raw = (
        "fixture-opt-B",
        "FIXTURE",
        "01",
        "Option B",
        "Second",
        time,
        None,
        "fixture://notice",
        "Water, Panthenol",
        time,
        None,
    )
    entries = [(1, "Water", 1), (2, "Panthenol", 2)]
    mapping = IngredientMapping(
        productId="oy-fixture",
        shadeId="01-2",
        optionId="fixture-opt-B",
        goodsNo="FIXTURE",
        mappingStatus="reproduced",
        mappingMethod="generator_replay",
        generationRecordId="SYNTHETIC:original-generation",
        sourceFingerprint="SYNTHETIC:source",
        generatorVersion="SYNTHETIC:generator",
        catalogFingerprint=catalog_fingerprint(*product, shades),
        sourceVersion=fingerprint([list(raw), [list(r) for r in entries]]),
        reviewStatus="verified",
        ingredientCoverage="full",
        normalizationStatus="verified",
        synthetic=True,
    )
    return product, shades, raw, entries, mapping


def setup(client, data, pages=None):
    p, shades, raw, entries, mapping = data
    session = Session(pages if pages is not None else [[p], shades, [raw], entries, [], []])
    service = IngredientService(IngredientRepository(session, [mapping]))
    client.app.dependency_overrides[get_ingredient_service] = lambda: service
    return session


def get(client, **params):
    return client.get("/api/products/oy-fixture/ingredients", params={"shadeId": "01-2", **params})


@pytest.mark.parametrize(
    "name,op,verdict", [("Panthenol", "includes", "MATCH"), ("Fragrance", "excludes", "UNKNOWN")]
)
def test_verified_presence_unresolved_absence_and_order(client, data, name, op, verdict):
    session = setup(client, data)
    response = get(client, ingredientName=name, operator=op)
    assert response.status_code == 200
    body = response.json()
    assert body["optionId"] == "fixture-opt-B" and body["mappingStatus"] == "reproduced"
    assert body["verdict"] == verdict and body["synthetic"]
    assert body["reason"] == body["conditions"][0]["reason"]
    assert body["reason"] == (
        "ingredient_present" if verdict == "MATCH" else "ingredient_identity_unresolved"
    )
    assert [i["sequence"] for i in body["ingredients"]] == [1, 2]
    assert "evidence" not in body and len(session.statements) == 6
    assert "ORDER BY raw_oy_option_ingredient.seq" in str(session.statements[3])
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("status", ["candidate", "ambiguous", "unmapped", "mismatch"])
def test_candidates_never_become_verified_or_read_raw_rows(client, data, status):
    data[-1].mapping_status = status
    session = setup(client, data)
    body = get(client).json()
    assert body["verdict"] == "UNKNOWN" and body["ingredients"] == []
    assert body["optionId"] is None and len(session.statements) == 2


def test_no_shade_and_missing_product_are_distinct(client, data):
    setup(client, data)
    body = client.get("/api/products/oy-fixture/ingredients").json()
    assert body["reason"] == "shade_required" and body["shadeId"] is None
    setup(client, data, [[]])
    assert get(client).status_code == 404
    setup(client, data)
    response = get(client, shadeId="missing")
    assert response.status_code == 404 and response.json()["code"] == "shade_not_found"


def test_other_product_option_is_rejected(client, data):
    session = setup(client, data)
    assert get(client, optionId="foreign").json()["reason"] == "option_mismatch"
    assert len(session.statements) == 2
    p, shades, raw, entries, mapping = data
    setup(client, (p, shades, (raw[0], "FOREIGN", *raw[2:]), entries, mapping))
    assert get(client).json()["reason"] == "option_ownership_or_source_mismatch"


@pytest.mark.parametrize("field", ["source_version", "catalog_fingerprint"])
def test_versions_must_match(client, data, field):
    setattr(data[-1], field, "SYNTHETIC:mismatch")
    setup(client, data)
    body = get(client).json()
    assert body["mappingStatus"] == "mismatch" and body["verdict"] == "UNKNOWN"
    assert body["ingredients"] == []


def test_unreviewed_rows_are_not_public_facts(client, data):
    data[-1].review_status = "unreviewed"
    setup(client, data)
    body = get(client, ingredientName="Water").json()
    assert body["verdict"] == "UNKNOWN" and body["ingredients"] == []
    assert body["reviewStatus"] == "unreviewed"


def test_reviewed_partial_presence_and_unknown_absence(client, data):
    data[-1].ingredient_coverage = "partial"
    setup(client, data)
    assert (
        get(client, ingredientName="Fragrance", operator="excludes").json()["verdict"] == "UNKNOWN"
    )
    setup(client, data)
    assert get(client, ingredientName="Panthenol").json()["verdict"] == "MATCH"


def test_sequence_gap_and_naive_source_time_require_review(client, data):
    p, shades, raw, entries, mapping = data
    entries = [(1, "Water", 1), (2, "Panthenol", 3)]
    mapping.source_version = fingerprint([list(raw), [list(r) for r in entries]])
    setup(client, (p, shades, raw, entries, mapping))
    body = get(client, ingredientName="Water").json()
    assert "ingredient_list_inconsistent" in body["issues"] and body["verdict"] == "UNKNOWN"
    naive = raw[9].replace(tzinfo=None)
    raw = (*raw[:9], naive, raw[10])
    mapping.source_version = fingerprint([list(raw), [list(r) for r in entries]])
    setup(client, (p, shades, raw, entries, mapping))
    body = get(client).json()
    assert body["collectedAt"] is None and body["collectedAtRaw"] == naive.isoformat()
    assert "source_timezone_unknown" in body["issues"]


def test_db_error_is_not_no_product(client, data):
    setup(client, data, [SQLAlchemyError("SYNTHETIC:failure")])
    response = get(client)
    assert response.status_code == 503 and response.json()["code"] == "ingredient_lookup_failed"
    assert "SYNTHETIC" not in response.text


def test_default_review_artifact_keeps_collected_catalog_unknown(client):
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    if not (root / "reports/ingredients/p0-2b-1-mapping.json").is_file():
        pytest.skip("Local review artifact unavailable")
    report = json.loads(
        (root / "reports/ingredients/p0-2b-1-mapping.json").read_text(encoding="utf-8")
    )
    record = next(r for r in report["records"] if r["mappingStatus"] == "candidate")
    seed = json.loads((root / "backend/api/seed/catalog.json").read_text(encoding="utf-8"))
    product = next(p for p in seed["products"] if p["id"] == record["productId"])
    session = Session(
        [
            [(product["id"], product["makeupZone"], product["texture"])],
            [(s["id"], s["name"], s["hex"]) for s in product["shades"]],
        ]
    )
    service = IngredientService(
        IngredientRepository(
            session, mapping_path=root / "reports/ingredients/p0-2b-1-mapping.json"
        )
    )
    client.app.dependency_overrides[get_ingredient_service] = lambda: service
    response = client.get(
        f"/api/products/{product['id']}/ingredients",
        params={"shadeId": record["shadeId"], "ingredientName": "Panthenol"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["mappingStatus"] == "candidate" and body["verdict"] == "UNKNOWN"
    assert body["ingredients"] == [] and body["optionId"] is None
    assert body["reviewStatus"] == "unreviewed" and body["synthetic"] is False
    assert len(session.statements) == 2  # no unverified raw option lookup


def artifact_service(client, data, path=None):
    product, shades, raw, entries, _ = data
    session = Session([[product], shades, [raw], entries, [], []])
    service = IngredientService(IngredientRepository(session, mapping_path=path))
    client.app.dependency_overrides[get_ingredient_service] = lambda: service
    return session


def write_artifact(tmp_path, data, *, version=1, records=None):
    path = tmp_path / "approved-mapping.json"
    path.write_text(
        json.dumps(
            {
                "schemaVersion": version,
                "records": records
                if records is not None
                else [data[-1].model_dump(mode="json", by_alias=True)],
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize("value", [None, "", "  ", "relative/report.json"])
def test_mapping_configuration_errors_are_not_unknown(client, data, monkeypatch, value):
    monkeypatch.delenv("INGREDIENT_MAPPING_PATH", raising=False)
    if value is not None:
        monkeypatch.setenv("INGREDIENT_MAPPING_PATH", value)
    session = artifact_service(client, data)
    response = get(client)
    assert response.status_code == 503
    expected = "path_invalid" if value and value.strip() else "not_configured"
    assert response.json()["code"] == "ingredient_mapping_" + expected
    assert len(session.statements) == 2


def test_missing_artifact_is_an_operational_error(client, data, tmp_path):
    artifact_service(client, data, tmp_path / "missing.json")
    response = get(client)
    assert response.status_code == 503
    assert response.json()["code"] == "ingredient_mapping_missing"
    assert str(tmp_path) not in response.text


@pytest.mark.parametrize(
    "content",
    [
        "{",
        "[]",
        '{"schemaVersion":1}',
        '{"schemaVersion":1,"records":{}}',
        '{"schemaVersion":1,"records":[{}]}',
    ],
)
def test_damaged_artifact_is_not_an_unverified_mapping(client, data, tmp_path, content):
    path = tmp_path / "damaged.json"
    path.write_text(content, encoding="utf-8")
    artifact_service(client, data, path)
    response = get(client)
    assert response.status_code == 503
    assert response.json()["code"] == "ingredient_mapping_invalid"


@pytest.mark.parametrize("version", [None, 2, True, "1"])
def test_artifact_schema_version_errors_are_explicit(client, data, tmp_path, version):
    path = write_artifact(tmp_path, data, version=version)
    artifact_service(client, data, path)
    response = get(client)
    assert response.status_code == 503
    assert response.json()["code"] == "ingredient_mapping_version_unsupported"


def test_unreadable_artifact_is_distinct_from_missing(client, data, tmp_path, monkeypatch):
    path = write_artifact(tmp_path, data)
    artifact_service(client, data, path)

    def denied(*args, **kwargs):
        raise PermissionError("SYNTHETIC: private path")

    monkeypatch.setattr(Path, "read_text", denied)
    response = get(client)
    assert response.status_code == 503
    assert response.json()["code"] == "ingredient_mapping_unavailable"
    assert "SYNTHETIC" not in response.text


def test_explicit_file_and_process_environment_ignore_working_directory(
    client,
    data,
    tmp_path,
    monkeypatch,
):
    path = write_artifact(tmp_path, data)
    runtime = tmp_path / "srv" / "app"
    runtime.mkdir(parents=True)
    monkeypatch.chdir(runtime)
    monkeypatch.setenv("INGREDIENT_MAPPING_PATH", str(path))
    artifact_service(client, data)
    assert get(client, ingredientName="Water").json()["verdict"] == "MATCH"
    # Explicit dependency injection takes precedence over a bad deployment environment.
    monkeypatch.setenv("INGREDIENT_MAPPING_PATH", "invalid-relative-path")
    artifact_service(client, data, path)
    assert get(client, ingredientName="Water").json()["verdict"] == "MATCH"


@pytest.mark.parametrize(
    "module_path",
    [
        "/app/app/repositories/ingredient_repository.py",
        "/ingredient_repository.py",
        "/srv/releases/vishue/backend/api/app/repositories/ingredient_repository.py",
    ],
)
def test_module_import_never_depends_on_parent_depth(module_path):
    import app.repositories.ingredient_repository as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    namespace = {"__file__": module_path, "__name__": "ingredient_depth_test"}
    exec(compile(source, module_path, "exec"), namespace)
    repository = namespace["IngredientRepository"](Session([]), [])
    assert repository._mapping("missing", "missing") is None


def test_empty_verified_artifact_means_unknown_not_server_failure(client, data, tmp_path):
    path = write_artifact(tmp_path, data, records=[])
    session = artifact_service(client, data, path)
    response = get(client, ingredientName="Water")
    assert response.status_code == 200
    assert response.json()["verdict"] == "UNKNOWN"
    assert response.json()["reason"] == "mapping_not_available"
    assert len(session.statements) == 2


def test_candidate_file_cannot_become_verified(client, data, tmp_path):
    data[-1].mapping_status = "candidate"
    data[-1].review_status = "unreviewed"
    path = write_artifact(tmp_path, data)
    session = artifact_service(client, data, path)
    response = get(client, ingredientName="Water")
    assert response.status_code == 200
    assert response.json()["verdict"] == "UNKNOWN"
    assert response.json()["reason"] == "mapping_not_verified"
    assert len(session.statements) == 2


def test_duplicate_artifact_records_are_invalid(client, data, tmp_path):
    record = data[-1].model_dump(mode="json", by_alias=True)
    path = write_artifact(tmp_path, data, records=[record, record])
    artifact_service(client, data, path)
    response = get(client)
    assert response.status_code == 503
    assert response.json()["code"] == "ingredient_mapping_invalid"


def test_source_and_catalog_version_mismatch_stay_unknown_from_file(client, data, tmp_path):
    for field, reason in [
        ("catalog_fingerprint", "catalog_version_mismatch"),
        ("source_version", "source_version_mismatch"),
    ]:
        original = getattr(data[-1], field)
        setattr(data[-1], field, "SYNTHETIC:wrong-version")
        path = write_artifact(tmp_path, data)
        artifact_service(client, data, path)
        response = get(client, ingredientName="Water")
        assert response.status_code == 200
        assert response.json()["verdict"] == "UNKNOWN" and response.json()["reason"] == reason
        setattr(data[-1], field, original)


def test_dotenv_mapping_path_is_used_without_exporting_environment(
    client, data, tmp_path, monkeypatch
):
    path = write_artifact(tmp_path, data)
    monkeypatch.delenv("INGREDIENT_MAPPING_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(f"INGREDIENT_MAPPING_PATH={path.as_posix()}\n", encoding="utf-8")
    artifact_service(client, data)
    assert get(client, ingredientName="Water").json()["verdict"] == "MATCH"


@pytest.mark.parametrize("synthetic", [True, False])
def test_production_blocks_only_synthetic_evidence(client, data, monkeypatch, synthetic):
    from types import SimpleNamespace

    monkeypatch.setattr(
        "app.services.ingredient_service.get_settings", lambda: SimpleNamespace(is_production=True)
    )
    data[-1].synthetic = synthetic
    setup(client, data)
    response = get(client, ingredientName="Water")
    body = response.json()
    assert response.status_code == 200
    assert body["synthetic"] is synthetic
    if synthetic:
        assert body["status"] == "unknown" and body["verdict"] == "UNKNOWN"
        assert body["reviewStatus"] == "unreviewed" and not body["ingredients"]
        assert body["reason"] == "synthetic_test_only" and body["evidenceId"] is None
        assert body["conditions"][0]["verdict"] == "UNKNOWN"
    else:
        assert body["status"] == "ok" and body["verdict"] == "MATCH"
        assert body["reviewStatus"] == "verified" and body["ingredients"]
