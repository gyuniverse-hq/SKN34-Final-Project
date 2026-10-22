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
        self.assertAlmostEqual(result["mse"], 17 / 3)
        self.assertAlmostEqual(result["r2"], 1 - 17 / 200)
        self.assertAlmostEqual(regression([10, 20, 30], [20, 40, 60])["pearson"], 1)
        self.assertEqual(result["truth"], [10, 20, 30])

    def test_classification_averages_match_sklearn_with_absent_grade(self):
        from sklearn.metrics import precision_recall_fscore_support
        truth, predicted = [0, 0, 0, 1, 2], [0, 0, 1, 1, 1]
        result = classification(truth, predicted, 4)
        for average in ("macro", "weighted"):
            expected = precision_recall_fscore_support(
                truth, predicted, labels=list(range(4)), average=average, zero_division=0)
            for key, value in zip(("precision", "recall", "f1"), expected[:3], strict=True):
                self.assertAlmostEqual(result[f"{average}_{key}"], value)

    def test_r2_is_not_forced_to_zero_for_poor_or_undefined_predictions(self):
        self.assertLess(regression([1, 2, 3], [10, 10, 10])["r2"], 0)
        for truth, prediction in [([1], [1]), ([1, 1], [1, 1]), ([1, 1], [2, 3])]:
            result = regression(truth, prediction)
            self.assertIsNone(result["r2"])
            self.assertIsNotNone(result["r2_undefined_reason"])

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
