"""Portable, local four-model analysis bundle; no HTTP or product ranking."""

import argparse
import importlib.metadata
import json
import shutil
from pathlib import Path

from server.acne.engine import AcneEngine

from .catalog import validate_model
from .engine import Engine, sha256
from .profile import FEATURES, run_profile

BUNDLE_SCHEMA = "skin-recommendation-models-v1"
OUTPUT_SCHEMA = "skin-recommendation-features-v1"
INDICATORS = ("acne", "pore", "pigmentation", "wrinkle")
EXCLUDED = ("moisture", "elasticity", "sagging", "dryness")
SELECTED_FEATURES = {key: FEATURES[key] for key in
                     ("pore_grade", "pigmentation_grade", "wrinkle_grade")}
TASKS = {spec[0] for spec in SELECTED_FEATURES.values()}


def _validate_selection(config):
    models = config.get("models", [])
    if len(models) != 3 or {model.get("task") for model in models} != TASKS:
        raise ValueError("Exactly the pore, pigmentation and wrinkle grade models are required")
    for model in models:
        validate_model(model)
    if len({model["id"] for model in models}) != 3:
        raise ValueError("Model IDs must be unique")
    acne = config.get("acne")
    if (not isinstance(acne, dict) or not isinstance(acne.get("checkpoint"), str)
            or not isinstance(acne.get("sha256"), str) or len(acne["sha256"]) != 64):
        raise ValueError("Acne checkpoint and SHA-256 are required")


def export_bundle(config_path, output):
    """Copy only four verified weight files; never overwrite existing exports."""
    config_path = Path(config_path).resolve(strict=True)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    selected = {"models": [dict(m) for m in config.get("models", []) if m.get("task") in TASKS],
                "acne": {key: (config.get("acne") or {}).get(key) for key in ("checkpoint", "sha256")}}
    _validate_selection(selected)
    records = [*selected["models"], selected["acne"]]
    sources = []
    for record in records:
        source = Path(record["checkpoint"])
        source = (source if source.is_absolute() else config_path.parent / source).resolve(strict=True)
        if sha256(source) != record["sha256"].lower():
            raise ValueError("Source checkpoint hash mismatch")
        sources.append(source)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / "weights").mkdir()
    for record, source in zip(records, sources):
        name = record["task"].split("/")[1] + ".bin" if "task" in record else "acne.pt"
        relative = "weights/" + name
        target = output / relative
        shutil.copyfile(source, target)
        if sha256(target) != record["sha256"].lower():
            raise ValueError("Exported checkpoint hash mismatch")
        record["checkpoint"] = relative
    manifest = dict(schema=BUNDLE_SCHEMA, indicators=list(INDICATORS),
                    excluded=list(EXCLUDED), output_schema=OUTPUT_SCHEMA,
                    purpose="local_research_inference_only_not_a_product_recommender",
                    validation_status="experimental_unvalidated",
                    runtime={name: importlib.metadata.version(name) for name in
                             ("torch", "torchvision", "numpy", "Pillow", "opencv-python-headless")},
                    **selected)
    # The manifest is written last; a partial export cannot be loaded as a bundle.
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def bundle_config(bundle_directory):
    """Resolve a portable manifest without relying on machine-specific settings."""
    root = Path(bundle_directory).resolve(strict=True)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if (manifest.get("schema") != BUNDLE_SCHEMA
            or manifest.get("output_schema") != OUTPUT_SCHEMA
            or manifest.get("indicators") != list(INDICATORS)
            or manifest.get("excluded") != list(EXCLUDED)):
        raise ValueError("Unsupported model bundle contract")
    _validate_selection(manifest)
    for record in [*manifest["models"], manifest["acne"]]:
        relative = Path(record["checkpoint"])
        if relative.is_absolute():
            raise ValueError("Bundle checkpoints must be relative paths")
        target = (root / relative).resolve(strict=True)
        if not target.is_relative_to(root) or not target.is_file():
            raise ValueError("Checkpoint must stay inside the bundle directory")
        if sha256(target) != record["sha256"].lower():
            raise ValueError("Bundle checkpoint hash mismatch")
        record["checkpoint"] = str(target)
    return dict(models=manifest["models"], acne=manifest["acne"],
                dataset_roots=[], allow_dataset_previews=False, metadata_evidence=None)


class RecommendationAnalyzer:
    """Load once per process. Pass local image bytes to analyze()."""

    def __init__(self, bundle_directory, *, region_locator=None):
        self.region_locator = region_locator
        manifest = bundle_config(bundle_directory)
        self.engines = {m["id"]: Engine(m) for m in manifest["models"]}
        self.acne = AcneEngine(manifest["acne"])

    def analyze(self, raw):
        options = {}
        if getattr(self, "region_locator", None) is not None:
            options["region_locator"] = self.region_locator
        report = run_profile(raw, self.engines, {"completed": 0}, self.acne,
                             features=SELECTED_FEATURES, unsupported=("acne",),
                             include_previews=False, **options)
        return dict(**{**report["ml_input"], "schema_version": OUTPUT_SCHEMA},
                    status=report["status"], indicators=list(INDICATORS))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export")
    export.add_argument("--config", required=True)
    export.add_argument("--output", required=True)
    infer = commands.add_parser("infer")
    infer.add_argument("--bundle", required=True)
    infer.add_argument("--image", required=True)
    args = parser.parse_args()
    if args.command == "export":
        print(export_bundle(args.config, args.output))
    else:
        result = RecommendationAnalyzer(args.bundle).analyze(Path(args.image).read_bytes())
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
