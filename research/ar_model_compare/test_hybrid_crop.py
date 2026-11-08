"""Test crop geometry, boundary restoration, and SAM 2 prompts on synthetic inputs.

Input: in-memory arrays; output: unittest assertions (no model needed).
Run: research/ar_evaluation/.venv/Scripts/python.exe -m unittest discover -s research/ar_model_compare -p 'test_*.py'
"""
import unittest

import numpy as np

from hybrid_crop import geometry, restore, sample
from sam2_prompts import make_prompts


class CropTest(unittest.TestCase):
    def test_crop_and_inverse(self):
        image = np.zeros((100, 100), np.uint8); image[40:60, 30:70] = 255
        box = geometry([[30, 40], [70, 60]], 40)
        self.assertEqual(box, (18.0, 18.0, 64.0))
        result = restore(sample(image, box, 256), box, image.shape)
        self.assertGreater((result > 0).sum(), 700)
        self.assertLess((result > 0).sum(), 900)
        self.assertTrue(result[50, 50])
        self.assertFalse(result[10, 10])

    def test_invalid_coordinates(self):
        with self.assertRaises(ValueError):
            geometry([[float('nan'), 4]], 3)

    def test_sam_prompts_stay_in_image(self):
        theta = np.linspace(np.pi, -np.pi, 20, endpoint=False)
        outer = np.column_stack((50 + 30*np.cos(theta), 50 + 12*np.sin(theta)))
        inner = np.column_stack((50 + 20*np.cos(theta), 50 + 3*np.sin(theta)))
        prompt = make_prompts(outer, inner, (100, 100))
        self.assertIn(1, prompt['labels']); self.assertIn(0, prompt['labels'])
        self.assertEqual(len(prompt['points']), len(prompt['labels']))
        for x, y in prompt['points']:
            self.assertTrue(0 <= x < 100 and 0 <= y < 100)


if __name__ == '__main__':
    unittest.main()
