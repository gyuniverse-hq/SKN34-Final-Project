import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from scripts.data.recommendation.train_v2_final import (
    FEATURES,
    load_final_data,
    ranking_metrics,
)


class FinalTrainingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.schema = self.root / "schema.json"
        self.schema.write_text(
            json.dumps(
                {
                    "labels": [{"db_id": i} for i in range(6)],
                    "categories": {k: ["value"] for k in FEATURES[:4]},
                }
            ),
            encoding="utf-8",
        )
        (self.root / "protocol.json").write_text(
            json.dumps(
                {
                    "image_model_features": FEATURES,
                    "replace_condition": True,
                    "label_count": 6,
                    "counts": {p: 1 for p in ("training", "validation", "test")},
                }
            ),
            encoding="utf-8",
        )
        for part in ("training", "validation", "test"):
            self.row = {
                "source": part,
                "group_id": part,
                "original_group_id": part,
                "image_group_id": part,
                "base_x": {
                    **{k: "value" for k in FEATURES[:4]},
                    "initial_skin_condition": "DO_NOT_USE",
                },
                "image_features": ["양호", "주의", "양호"],
                "y": [1, 0, 0, 0, 0, 0],
            }
            self.write(part, self.row)

    def write(self, part, row):
        (self.root / f"{part}.jsonl").write_text(json.dumps(row), encoding="utf-8")

    def test_final_features_exclude_original_condition(self):
        _, _, data, _ = load_final_data(self.root, self.schema)
        self.assertEqual(data["training"][1].shape, (1, 7))
        self.assertNotIn("DO_NOT_USE", data["training"][1])

    def test_image_group_leakage_rejected(self):
        self.write("test", {**self.row, "image_group_id": "training"})
        with self.assertRaisesRegex(ValueError, "Cross-split leakage: image_group_id"):
            load_final_data(self.root, self.schema)

    def test_target_overflow_not_silently_cast_to_zero(self):
        self.write("test", {**self.row, "y": [256, 0, 0, 0, 0, 0]})
        with self.assertRaisesRegex(ValueError, "Invalid multi-hot"):
            load_final_data(self.root, self.schema)

    def test_rank_metric_ties_use_database_id(self):
        result = ranking_metrics(
            np.array([[0, 0, 1]]),
            np.array([[0.5, 0.5, 0.5]]),
            [{"db_id": 30}, {"db_id": 20}, {"db_id": 10}],
            k=1,
        )
        self.assertEqual(result, {"precision_at_1": 1.0, "recall_at_1": 1.0})
