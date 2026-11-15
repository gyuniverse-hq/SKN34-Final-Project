"""Small synthetic checks for the colour and geometry used in the study."""

import unittest

import numpy as np

import analyze_blush


class AnalysisTest(unittest.TestCase):
    def test_srgb_round_trip_keeps_dark_and_bright_values(self):
        rgb = np.array([[[0, 1, 10], [11, 128, 255], [240, 50, 20]]], dtype=np.uint8)
        reconstructed = analyze_blush.srgb(analyze_blush.linear(rgb)) * 255
        np.testing.assert_allclose(reconstructed, rgb, atol=0.001)

    def test_mesh_identity_keeps_interior_pixels_and_coverage(self):
        yy, xx = np.indices((64, 64))
        image = np.stack((xx / 64, yy / 64, (xx + yy) / 128), axis=2).astype(np.float32)
        points = np.array([[8, 8], [55, 8], [55, 55], [8, 55], [32, 32]], dtype=np.float32)
        warped, coverage = analyze_blush.warp_mesh(image, points, points, (64, 64))
        self.assertTrue(coverage[12:52, 12:52].all())
        np.testing.assert_allclose(warped[12:52, 12:52], image[12:52, 12:52], atol=1e-6)

    def test_mesh_does_not_fill_out_of_frame_source_with_black(self):
        image = np.ones((64, 64, 3), dtype=np.float32)
        dest = np.array([[8, 8], [55, 8], [55, 55], [8, 55], [32, 32]], dtype=np.float32)
        source = dest.copy()
        source[0] = [-4, 8]
        warped, coverage = analyze_blush.warp_mesh(image, source, dest, (64, 64))
        self.assertTrue(coverage.any())
        self.assertFalse(coverage[10, 10])
        np.testing.assert_allclose(warped[coverage], 1, atol=1e-6)

    def test_background_calibration_keeps_identical_images(self):
        rng = np.random.default_rng(2026)
        image = rng.integers(30, 220, size=(300, 500, 3), dtype=np.uint8)
        corrected, info = analyze_blush.calibrate_background(image, image)
        np.testing.assert_allclose(corrected, analyze_blush.linear(image), atol=1e-5)
        self.assertLess(max(info["background_validation_rmse_linear_rgb"]), 1e-5)


if __name__ == "__main__":
    unittest.main()
