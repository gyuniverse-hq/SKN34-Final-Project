import unittest
from unittest.mock import patch

import torch

from server.acne.engine import AcneEngine
from server.nia.profile import FEATURES, run_profile

from test_profile import FixtureEngine, geometry, image_bytes


class AcneIntegrationTests(unittest.TestCase):
    def engines(self):
        return {name: FixtureEngine(name, task, areas)
                for name, (task, areas) in FEATURES.items()}

    def test_optional_acne_preserves_all_original_results_and_exports_binary_semantics(self):
        class AcneFixture:
            def predict(self, raw):
                return dict(status="predicted", label=1, score=.8, threshold=.5,
                            model_sha256="b" * 64, score_type="sigmoid_uncalibrated")

        job = dict(completed=0)
        with patch("server.nia.profile.locate_regions", return_value=geometry()):
            report = run_profile(image_bytes(), self.engines(), job, AcneFixture())
        self.assertEqual(report["predicted"], 25)
        self.assertEqual(report["expected"], 25)
        self.assertEqual(job["completed"], 25)
        self.assertEqual(report["ml_input"]["schema_version"], "nia-photo-features-v2")
        self.assertEqual(report["ml_input"]["features"]["acne"], 1)
        self.assertEqual(report["ml_input"]["acne"]["score"], .8)
        self.assertEqual(report["ml_input"]["provenance"]["acne"]["unit"], "binary_label")
        self.assertEqual(report["ml_input"]["unsupported"], ["oiliness", "skin_type"])
        self.assertEqual(report["ml_input"]["features"]["dryness_lips"], 2)

    def test_invalid_acne_config_or_missing_weights_isolated_from_NIA(self):
        for config in ({}, {"checkpoint": "not-real.pt", "sha256": "0" * 64}):
            with self.subTest(config=config), patch(
                    "server.nia.profile.locate_regions", return_value=geometry()):
                report = run_profile(image_bytes(), self.engines(), dict(completed=0),
                                     AcneEngine(config, torch.device("cpu")))
            self.assertEqual(report["status"], "partial")
            self.assertEqual(report["predicted"], 24)
            self.assertEqual(report["acne"]["status"], "failed")
            self.assertIsNone(report["ml_input"]["features"]["acne"])
            self.assertEqual(report["ml_input"]["feature_status"]["acne"], "failed")

    def test_hash_mismatch_never_loads_weights(self):
        engine = AcneEngine({"checkpoint": __file__, "sha256": "0" * 64}, torch.device("cpu"))
        with patch("server.acne.engine.load_bundle") as loader:
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                engine.predict(image_bytes())
            loader.assert_not_called()


if __name__ == "__main__":
    unittest.main()
