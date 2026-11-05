import json
import tempfile
import unittest
from pathlib import Path

import torch

from server.nia.benchmark import batch_predict, score_rows, task_audit


class BenchmarkTests(unittest.TestCase):
    def test_batches_preserve_order_and_binary_threshold_and_original_units(self):
        records = [dict(id=str(i), area="fixture", truth=i % 2) for i in range(5)]

        def prepare(row):
            return torch.tensor([[float(row["truth"])]])

        class BinaryModel(torch.nn.Module):
            def forward(self, value):
                return value * 4 - 2

        rows = batch_predict(
            records, prepare, BinaryModel(), torch.device("cpu"), 2, 2, "binary", threshold=0.5
        )
        self.assertEqual([r["id"] for r in rows], [r["id"] for r in records])
        self.assertEqual([r["prediction"] for r in rows], [r["truth"] for r in records])
        rows = batch_predict(
            records,
            prepare,
            torch.nn.Identity(),
            torch.device("cpu"),
            2,
            2,
            "regression",
            multiplier=100,
        )
        self.assertEqual([r["prediction"] for r in rows], [0, 100, 0, 100, 0])

    def test_continuous_accuracy_is_not_invented_and_empty_subset_is_null(self):
        rows = [dict(truth=1.0, prediction=2.0), dict(truth=2.0, prediction=1.0)]
        result = score_rows(rows, "regression")
        self.assertIsNone(result["accuracy"])
        self.assertEqual(result["mse"], 1)
        self.assertEqual(result["rmse"], 1)
        self.assertEqual(result["r2"], -3)
        self.assertNotIn("pearson", result)
        self.assertIsNone(score_rows([], "regression"))
        binary = score_rows([dict(truth=0, prediction=1)], "class", 2, ordinal=False)
        self.assertNotIn("within_one", binary)

    def test_overlap_is_scoped_to_current_task_and_missing_rois_are_counted(self):
        def identifier(subject, part=5):
            return f"Sub_{subject}_Equ_3_Angle_0_Area_{part}"

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "split/class/smart_phone"
            folder.mkdir(parents=True)
            datasets = {
                "train": {"pore": [identifier("0001")], "other_task": [identifier("0002")]},
                "val": {"pore": [identifier("0003")], "other_task": []},
                "test": {"pore": [identifier("0002"), identifier("0004")], "other_task": []},
                "available_test": {"pore": [identifier("0002")], "other_task": []},
            }
            for name, data in datasets.items():
                (folder / f"1_{name}set_info.json").write_text(json.dumps(data))
            audit = task_audit(
                root, "class", "smart_phone", ["pore"], [dict(id=identifier("0002"))]
            )
            self.assertEqual(audit["excluded_rois"], 1)
            self.assertEqual(audit["comparisons"]["train"]["subject_overlap"], 0)
            self.assertEqual(audit["no_train_val_overlap_subjects"], 1)
            with self.assertRaisesRegex(ValueError, "declared available"):
                task_audit(root, "class", "smart_phone", ["pore"], [dict(id=identifier("0004"))])
            (folder / "1_trainset_info.json").write_text(
                json.dumps({"wrinkle": [identifier("0002")]})
            )
            (folder / "1_valset_info.json").write_text(json.dumps({"wrinkle": []}))
            aggregated = task_audit(
                root,
                "class",
                "smart_phone",
                ["pore"],
                [dict(id=identifier("0002"))],
                task="class/wrinkle",
            )
            self.assertEqual(aggregated["comparisons"]["train"]["subject_overlap"], 1)
            self.assertEqual(aggregated["no_train_val_overlap_subjects"], 0)


if __name__ == "__main__":
    unittest.main()
