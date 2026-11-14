import asyncio
import importlib.util
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from app.core.config import PROJECT_ROOT, Settings, model_project_root
from app.services.recommendation_comparison_service import ComparisonService
from app.services.recommendation_v2_service import recommend_v2
from tests.test_recommendation_comparison import body, catalog


def script_module(name):
    path = PROJECT_ROOT / "scripts/data/recommendation" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def clean_model_env():
    with patch.dict(os.environ):
        for key in ("RECOMMENDATION_MODEL", "RECOMMENDATION_MODELS_DIR", "NODE_ENV"):
            os.environ.pop(key, None)
        yield


def test_default_and_named_models_share_the_skin_model_parent_without_cwd_dependency(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    settings = Settings(_env_file=None)
    assert settings.recommendation_bundle_path == PROJECT_ROOT / "ml/runs/recommend-cat-v3/bundle"
    changed = Settings(_env_file=None, recommendation_model="recommend-cat-v2")
    assert changed.recommendation_bundle_path == PROJECT_ROOT / "ml/runs/recommend-cat-v2/bundle"
    assert changed.recommendation_v2_bundle == str(changed.recommendation_bundle_path)
    relative = Settings(_env_file=None, recommendation_models_dir="custom-models")
    assert (
        relative.recommendation_bundle_path
        == PROJECT_ROOT / "custom-models/recommend-cat-v3/bundle"
    )
    mounted = Settings(_env_file=None, recommendation_models_dir=tmp_path)
    assert mounted.recommendation_bundle_path == tmp_path / "recommend-cat-v3/bundle"


@pytest.mark.parametrize("name", ["", "../outside", "bad/name", "bad\\name", "UPPER", " leading"])
def test_invalid_model_name_is_not_silently_replaced(name):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, recommendation_model=name)


def test_docker_api_layout_does_not_assume_a_full_repository():
    assert model_project_root(Path("/app")) == Path("/app")
    assert model_project_root(Path("/repo/backend/api")) == Path("/repo")


def test_project_dotenv_priority_matches_skin_selection_and_preserves_other_environment(
    tmp_path, monkeypatch
):
    names = [".env", ".env.development", ".env.local", ".env.development.local"]
    for index, name in enumerate(names):
        (tmp_path / name).write_text(
            f"RECOMMENDATION_MODEL=recommend-cat-v{index + 2}\n", encoding="utf-8"
        )
    monkeypatch.setenv("DATABASE_URL", "unchanged")
    module = script_module("run_v2_comparison")
    module.configure_model_environment(tmp_path)
    assert Settings(_env_file=None).recommendation_model == "recommend-cat-v5"
    assert os.environ["DATABASE_URL"] == "unchanged"
    monkeypatch.setenv("RECOMMENDATION_MODEL", "recommend-cat-v6")
    module.configure_model_environment(tmp_path)
    assert Settings(_env_file=None).recommendation_model == "recommend-cat-v6"
    monkeypatch.delenv("RECOMMENDATION_MODEL")
    monkeypatch.setenv("NODE_ENV", "production")
    (tmp_path / ".env.production.local").write_text(
        "RECOMMENDATION_MODEL=recommend-cat-v7\n", encoding="utf-8"
    )
    module.configure_model_environment(tmp_path)
    assert Settings(_env_file=None).recommendation_model == "recommend-cat-v7"


def test_selected_name_and_path_reach_inference():
    repo = AsyncMock()
    repo.read.return_value = catalog()
    settings = Settings(_env_file=None, recommendation_model="recommend-cat-v3")
    with (
        patch(
            "app.services.recommendation_comparison_service.fetch_v1",
            new=AsyncMock(return_value={"matches": []}),
        ),
        patch(
            "app.services.recommendation_comparison_service.recommend_v2",
            return_value={"status": "ok", "matches": []},
        ) as infer,
    ):
        asyncio.run(ComparisonService(repo, settings).compare(body()))
    assert infer.call_args.args[3] == str(settings.recommendation_bundle_path)
    assert infer.call_args.kwargs["model_name"] == "recommend-cat-v3"


def test_wrong_manifest_name_fails_before_prediction():
    with (
        patch(
            "app.services.recommendation_v2_service.load_bundle",
            return_value=(None, {"version": "recommend-cat-v3"}),
        ),
        patch("app.services.recommendation_v2_service.predict_seeds") as predict,
        pytest.raises(ValueError, match="recommendation_model_name_mismatch"),
    ):
        recommend_v2(body(), "pores", catalog(), "unused", model_name="recommend-cat-v2")
    predict.assert_not_called()


def test_export_destination_matches_runtime_selection(tmp_path):
    exporter = script_module("export_v2_bundle")
    for name in ("recommend-cat-v2", "recommend-cat-v3"):
        settings = Settings(_env_file=None, recommendation_model=name)
        assert exporter.bundle_destination(name) == settings.recommendation_bundle_path
    assert exporter.bundle_destination("recommend-cat-v2", tmp_path) == tmp_path
    with pytest.raises(ValueError, match="Model name"):
        exporter.bundle_destination("../outside")
