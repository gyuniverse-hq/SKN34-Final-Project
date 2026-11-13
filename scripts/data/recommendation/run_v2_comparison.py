"""Local comparison API / smoke checks. Signed-in recorded runs write V2 feedback history."""

import argparse
import csv
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[3]


def configure_model_environment(root=ROOT):
    """Read the same project dotenv priority as skin-models.cjs; export model settings only."""
    from app.core.config import Settings

    mode = "production" if os.environ.get("NODE_ENV") == "production" else "development"
    settings = Settings(
        _env_file=(
            root / ".env",
            root / f".env.{mode}",
            root / ".env.local",
            root / f".env.{mode}.local",
        ),
        _env_file_encoding="utf-8",
    )
    os.environ["RECOMMENDATION_MODEL"] = settings.recommendation_model
    os.environ["RECOMMENDATION_MODELS_DIR"] = str(settings.recommendation_models_dir)


def docker_settings():
    api, db = json.loads(
        subprocess.check_output(
            ["docker", "inspect", "vishue-api-1", "vishue-postgres-1"]
        )
    )
    values = dict(item.split("=", 1) for item in api["Config"]["Env"] if "=" in item)
    url = urlsplit(values["DATABASE_URL"])
    port = db["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostPort"]
    # Preserve credentials in memory; never emit the URL or Docker environment.
    authority = url.netloc.rsplit("@", 1)[0] + "@127.0.0.1:" + port
    os.environ["DATABASE_URL"] = urlunsplit(
        ("postgresql+asyncpg", authority, url.path, url.query, url.fragment)
    )
    os.environ["RECOMMENDATION_V1_REVISION"] = api["Image"]
    # Reuse only public token-verification settings; never copy the admin secret key.
    for key in ("SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY"):
        if values.get(key):
            os.environ.setdefault(key, values[key])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker-local", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8082)
    parser.add_argument("--smoke-output", type=Path)
    args = parser.parse_args()
    if args.docker_local:
        docker_settings()
    os.environ["ENV"] = "local"
    os.environ["RECOMMENDATION_COMPARISON_ENABLED"] = "true"
    sys.path.insert(0, str(ROOT / "backend/api"))
    configure_model_environment()
    os.environ.setdefault(
        "CORS_ORIGINS",
        json.dumps(
            [
                "http://localhost:8081",
                "http://127.0.0.1:8081",
                "http://localhost:8083",
                "http://127.0.0.1:8083",
            ]
        ),
    )
    if args.smoke_output:
        from fastapi.testclient import TestClient

        from app.main import create_app

        if args.smoke_output.exists():
            raise ValueError("Choose a new smoke output path")
        source = ROOT / "ml/data/recommendation-v2/model-ready-20261111/x_metadata.csv"
        with source.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        examples = {}
        for row in rows:
            if row["included_in_x"] != "true":
                continue
            scores = {
                "pores": float(row["pore_score"]),
                "pigmentation": float(row["pigmentation_score"]),
                "wrinkles": float(row["wrinkle_score"]),
            }
            goal = max(scores, key=scores.get)
            examples.setdefault(
                goal,
                {
                    "ageGroup": row["age_group"],
                    "gender": row["gender"],
                    "skinType": row["skin_type"],
                    "scores": scores,
                    "analysisVersion": "skin-analysis-v4",
                    "scoreKind": "binary_caution_probability",
                    "aggregation": "mean-cheeks-pore-tone-eyes-wrinkle-v1",
                },
            )
        results = []
        with TestClient(create_app()) as client:
            for body in examples.values():
                response = client.post("/api/dev/recommendations/compare", json=body)
                response.raise_for_status()
                result = response.json()
                if result["v1"]["status"] != "ok" or result["v2"]["status"] != "ok":
                    raise ValueError(
                        "Comparison branch failed: "
                        + json.dumps(
                            {"v1": result["v1"]["status"], "v2": result["v2"]["status"]}
                        )
                    )
                if not result["sameSnapshot"]:
                    raise ValueError("V1/V2 snapshot mismatch")
                results.append(result)
                print(
                    json.dumps(
                        {
                            "goal": result["targetConcern"],
                            "core": len(result["v2"]["coreIngredients"]),
                            "expanded": len(result["v2"]["expandedIngredients"]),
                            "candidates": result["v2"]["candidateProducts"],
                            "v1Products": len(result["v1"]["matches"]),
                            "v2Products": len(result["v2"]["matches"]),
                        }
                    )
                )
        args.smoke_output.parent.mkdir(parents=True, exist_ok=True)
        args.smoke_output.write_text(
            json.dumps(
                {
                    "purpose": (
                        "integration smoke, source metadata examples, not user-photo validation"
                    ),
                    "results": results,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    else:
        import uvicorn

        uvicorn.run("app.main:app", host=args.host, port=args.port, access_log=False)


if __name__ == "__main__":
    main()
