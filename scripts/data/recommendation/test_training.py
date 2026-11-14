import unittest

import numpy as np

from scripts.data.recommendation.training_common import evaluate, select_threshold


class TrainingMetricTests(unittest.TestCase):
    def test_absent_test_class_is_visible_in_macro_and_confusion(self):
        y = np.array([[1, 0, 0], [0, 1, 0]], dtype=np.uint8)
        scores = np.array([[0.9, 0.1, 0.8], [0.1, 0.9, 0.8]])
        labels = [{"db_id": i, "name": str(i)} for i in range(3)]
        metrics, per_label, matrices, pred = evaluate(y, scores, 0.5, labels)
        self.assertAlmostEqual(metrics["f1_macro"], 2 / 3)
        self.assertAlmostEqual(metrics["f1_macro_supported"], 1.0)
        self.assertAlmostEqual(metrics["precision_micro"], 0.5)
        self.assertAlmostEqual(metrics["recall_micro"], 1.0)
        self.assertEqual(matrices[2].tolist(), [[0, 2], [0, 0]])
        self.assertEqual(per_label[2]["support"], 0)
        self.assertEqual(pred.shape, y.shape)

    def test_threshold_selection_is_deterministic_and_validation_only(self):
        y = np.array([[1, 0], [0, 1]])
        scores = np.array([[0.8, 0.2], [0.2, 0.8]])
        best, trials = select_threshold(y, scores)
        self.assertAlmostEqual(best["threshold"], 0.5)
        self.assertAlmostEqual(best["macro_f1"], 1.0)
        self.assertEqual(len(trials), 29)


if __name__ == "__main__":
    unittest.main()
