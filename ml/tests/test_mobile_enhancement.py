import numpy as np
import pytest
import torch
from PIL import Image, ImageEnhance, ImageFilter

from skin_analysis.mobile_enhancement import RoiEnhancement


@pytest.mark.parametrize("seed", [0, 1, 42])
def test_embedded_enhancement_matches_pillow_pixels(seed):
    rgb = np.random.default_rng(seed).integers(0, 256, (256, 256, 3), dtype=np.uint8)
    reference = ImageEnhance.Contrast(Image.fromarray(rgb).filter(
        ImageFilter.UnsharpMask(radius=1, percent=75, threshold=0))).enhance(1.4)
    enhancement = RoiEnhancement()
    raw = torch.from_numpy(rgb.copy()).permute(2, 0, 1).unsqueeze(0)
    actual = enhancement.enhance(raw)[0].permute(1, 2, 0).numpy()
    np.testing.assert_array_equal(actual, np.asarray(reference))
    normalized = (raw.float() / 255 - enhancement.mean) / enhancement.std
    expected = (torch.from_numpy(np.array(reference)).permute(2, 0, 1).unsqueeze(0)
                .float() / 255 - enhancement.mean) / enhancement.std
    torch.testing.assert_close(enhancement(normalized), expected, rtol=0, atol=0)
