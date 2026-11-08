"""Exercise mask metrics, empty cases, and reproducible bootstrap intervals.

Input: in-memory synthetic masks; output: unittest result.
Run: research/ar_evaluation/.venv/Scripts/python.exe -m unittest discover -s research/ar_model_compare -p 'test_*.py'
"""
import unittest

import numpy as np

from metrics_a import bootstrap_median, measure


class MetricsTest(unittest.TestCase):
    def test_known_overlap(self):
        gt = np.zeros((9, 9), bool); gt[2:5, 2:5] = True
        pred = np.zeros_like(gt); pred[2:5, 3:6] = True
        result = measure(pred, gt, 10)
        self.assertAlmostEqual(result["iou"], .5)
        self.assertAlmostEqual(result["dice"], 2/3)
        self.assertAlmostEqual(result["spill"], 1/3)
        self.assertAlmostEqual(result["miss"], 1/3)
        self.assertGreater(result["boundary_px"], 0)
        self.assertAlmostEqual(result["boundary_mouth_pct"], result["boundary_px"] * 10)

    def test_empty_is_not_perfect(self):
        empty = np.zeros((4, 4), bool)
        result = measure(empty, empty, 10)
        self.assertIsNone(result["iou"])
        self.assertIsNone(result["boundary_px"])

    def test_bootstrap_deterministic(self):
        first = bootstrap_median([1, 2, 3, 4])
        self.assertEqual(first, bootstrap_median([1, 2, 3, 4]))
        self.assertEqual(first["median"], 2.5)


if __name__ == "__main__":
    unittest.main()
