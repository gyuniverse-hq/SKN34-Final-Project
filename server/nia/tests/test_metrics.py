"""Small artificial arrays verify math only; never model performance evidence."""

import math
import unittest

from server.nia.metrics import classification, regression, timing


class MetricsTests(unittest.TestCase):
    def test_ordinal_metrics_and_confusion(self):
        result = classification([0, 1, 2, 2], [0, 2, 1, 0], 3)
        self.assertEqual(result["confusion"], [[1, 0, 0], [0, 0, 1], [1, 1, 0]])
        self.assertEqual(result["accuracy"], .25)
        self.assertEqual(result["mae"], 1)
        self.assertEqual(result["within_one"], .75)
        self.assertAlmostEqual(result["macro_f1"], 2 / 9)
        self.assertEqual([g["support"] for g in result["per_grade"]], [1, 1, 2])
        self.assertEqual([g["predicted"] for g in result["per_grade"]], [2, 1, 1])
        self.assertEqual(result["per_grade"][0]["precision"], .5)
        self.assertEqual(result["per_grade"][0]["recall"], 1)

    def test_absent_grades_have_zero_f1(self):
        self.assertEqual(classification([0], [0], 7)["macro_f1"], 1 / 7)

    def test_reject_invalid_grades_and_lengths(self):
        for truth, prediction in [([], []), ([0], []), ([7], [0]), ([True], [0]), ([.5], [0])]:
            with self.subTest(truth=truth), self.assertRaises(ValueError):
                classification(truth, prediction, 7)

    def test_regression_uses_supplied_original_units(self):
        result = regression([10, 20, 30], [12, 18, 33])
        self.assertAlmostEqual(result["mae"], 7 / 3)
        self.assertAlmostEqual(result["rmse"], math.sqrt(17 / 3))
        self.assertAlmostEqual(regression([10, 20, 30], [20, 40, 60])["pearson"], 1)
        self.assertEqual(result["truth"], [10, 20, 30])

    def test_undefined_correlation(self):
        for truth, prediction in [([1], [2]), ([1, 1], [2, 3]), ([1, 2], [3, 3])]:
            self.assertIsNone(regression(truth, prediction)["pearson"])
        with self.assertRaises(ValueError):
            regression([1], [math.nan])

    def test_timing_percentile_interpolation(self):
        result = timing([1, 2, 3, 4, 100])
        self.assertEqual(result["mean_ms"], 22)
        self.assertEqual(result["p50_ms"], 3)
        self.assertAlmostEqual(result["p95_ms"], 80.8)
        self.assertIsNone(timing([]))


if __name__ == "__main__":
    unittest.main()
