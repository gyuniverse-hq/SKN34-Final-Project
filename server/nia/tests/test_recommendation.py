import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server.nia.profile import FEATURES
from server.nia.recommendation import (
    INDICATORS,
    OUTPUT_SCHEMA,
    RecommendationAnalyzer,
    bundle_config,
    export_bundle,
)

from test_profile import FixtureEngine, geometry, image_bytes


class AcneFixture:
    def __init__(self, fail=False):
        self.fail = fail

    def predict(self, raw):
        if self.fail:
            raise ValueError("fixture failure")
        return dict(status="predicted", label=0, score=0.0, threshold=.5,
                    model_sha256="b" * 64, score_type="sigmoid_uncalibrated")


class RecommendationTests(unittest.TestCase):
    def analyzer(self, fail_acne=False):
        analyzer = RecommendationAnalyzer.__new__(RecommendationAnalyzer)
        # Even if extra models are available, the selected pipeline must never call them.
        analyzer.engines = {name: FixtureEngine(name, task, areas)
                            for name, (task, areas) in FEATURES.items()}
        analyzer.acne = AcneFixture(fail_acne)
        return analyzer

    def test_only_four_indicators_are_run_without_collapsing_regions_or_losing_zero(self):
        analyzer = self.analyzer()
        with patch("server.nia.profile.locate_regions", return_value=geometry()):
            result = analyzer.analyze(image_bytes())
        self.assertEqual(result["schema_version"], OUTPUT_SCHEMA)
        self.assertEqual(result["indicators"], list(INDICATORS))
        self.assertEqual(result["status"], "complete")
        self.assertEqual(len(result["features"]), 10)
        self.assertEqual(result["features"]["acne"], 0)
        self.assertEqual(result["acne"]["score"], 0.0)
        self.assertFalse(result["training_roi_match"])
        self.assertEqual(result["unsupported"], [])
        self.assertEqual(result["provenance"]["pore_grade_cheek_image_left"]["grade_range"], [0, 2])
        self.assertIn("pore_grade_cheek_image_right", result["features"])
        for key, engine in analyzer.engines.items():
            self.assertEqual(bool(engine.calls), key in {"pore_grade", "pigmentation_grade", "wrinkle_grade"})

    def test_failed_acne_is_null_and_does_not_remove_grade_results(self):
        with patch("server.nia.profile.locate_regions", return_value=geometry()):
            result = self.analyzer(True).analyze(image_bytes())
        self.assertEqual(result["status"], "partial")
        self.assertIsNone(result["features"]["acne"])
        self.assertEqual(result["feature_status"]["acne"], "failed")
        self.assertEqual(result["feature_status"]["wrinkle_grade_forehead"], "predicted")

    def export_fixture(self, root):
        weights = root / "original.bin"
        weights.write_bytes(b"fixture-only-not-model-weights")
        digest = hashlib.sha256(weights.read_bytes()).hexdigest()
        models = []
        for key, count in (("pore_grade", 6), ("pigmentation_grade", 6), ("wrinkle_grade", 7)):
            task, areas = FEATURES[key]
            models.append(dict(id=key, task=task, architecture="resnet50", resolution=256,
                               grades=list(range(count)), areas=areas,
                               checkpoint=str(weights), sha256=digest,
                               source="unit-test fixture", label_evidence="unit-test fixture"))
        config = root / "config.json"
        config.write_text(json.dumps(dict(models=[*models, dict(task="regression/moisture",
                                                              checkpoint="must-not-be-opened.bin")],
                                         acne=dict(checkpoint=str(weights), sha256=digest))))
        return export_bundle(config, root / "bundle")

    def test_export_is_relocatable_excludes_other_weights_and_preserves_originals(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = self.export_fixture(root)
            relocated = root / "relocated"
            bundle.rename(relocated)
            analyzer = RecommendationAnalyzer(relocated)
            self.assertEqual(len(analyzer.engines), 3)
            self.assertEqual(len(list((relocated / "weights").iterdir())), 4)
            self.assertEqual((root / "original.bin").read_bytes(), b"fixture-only-not-model-weights")
            self.assertTrue(Path(analyzer.acne.config["checkpoint"]).is_relative_to(relocated))
            with self.assertRaises(FileExistsError):
                export_bundle(root / "config.json", relocated)

    def test_loader_rejects_extra_models_and_paths_outside_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = self.export_fixture(root)
            file = bundle / "manifest.json"
            manifest = json.loads(file.read_text())
            manifest["models"][0]["checkpoint"] = "../original.bin"
            file.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "inside the bundle"):
                RecommendationAnalyzer(bundle)
            manifest["models"].append(dict(task="regression/moisture"))
            file.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "Exactly"):
                RecommendationAnalyzer(bundle)

    def test_bundle_service_ignores_local_config_and_rejects_corrupt_weights(self):
        from server.nia.service import Service

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = self.export_fixture(root)
            with patch.dict("os.environ", {"NIA_EVAL_DEVICE": "cpu"}):
                service = Service(root / "missing-local-config.json", bundle_directory=bundle)
            self.assertTrue(all(str(engine.device) == "cpu" for engine in service.engines.values()))
            self.assertEqual(str(service.acne.device), "cpu")
            status = service.status()
            self.assertTrue(status["config_exists"])
            self.assertEqual(status["errors"], {})
            self.assertEqual(len(status["models"]), 3)
            self.assertTrue(all(model["present"] for model in status["models"]))
            self.assertTrue(status["acne"]["present"])
            self.assertFalse(status["dataset_configured"])
            self.assertEqual(set(service.profile_features),
                             {"pore_grade", "pigmentation_grade", "wrinkle_grade"})
            (bundle / "weights" / "acne.pt").write_bytes(b"corrupt")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                bundle_config(bundle)


if __name__ == "__main__":
    unittest.main()
