"""Pillow 12.3 UnsharpMask(1, 75, 0) + Contrast(1.4), embedded in exported ONNX.

Integer arithmetic preserves Pillow's per-pass rounding and edge replication.
References: Pillow libImaging/{BoxBlur,UnsharpMask,Convert,Blend}.c and ImageEnhance.py.
Pillow copyright and permission notice: docs/licenses/Pillow.txt.
"""

import torch
from torch import nn


class RoiEnhancement(nn.Module):
    def __init__(self):
        super().__init__()
        self.register_buffer("mean", torch.tensor([.485, .456, .406]).reshape(1, 3, 1, 1))
        self.register_buffer("std", torch.tensor([.229, .224, .225]).reshape(1, 3, 1, 1))

    def enhance(self, rgb):
        original = rgb.to(torch.int64)
        blurred = original
        # Gaussian radius 1, three box passes: fractional box radius .25.
        # These are Pillow's float32-derived 24-bit center/edge coefficients.
        for axis in (3, 2):
            for _ in range(3):
                low = torch.cat((blurred.narrow(axis, 0, 1),
                                 blurred.narrow(axis, 0, blurred.shape[axis] - 1)), axis)
                high = torch.cat((blurred.narrow(axis, 1, blurred.shape[axis] - 1),
                                  blurred.narrow(axis, blurred.shape[axis] - 1, 1)), axis)
                blurred = torch.div(blurred * 11184811 + (low + high) * 2796202 + (1 << 23),
                                    1 << 24, rounding_mode="trunc")
        sharpened = (original + torch.div((original - blurred) * 75, 100,
                                         rounding_mode="trunc")).clamp(0, 255)
        gray = torch.div(sharpened[:, 0:1] * 19595 + sharpened[:, 1:2] * 38470
                         + sharpened[:, 2:3] * 7471 + 32768, 65536, rounding_mode="trunc")
        count = rgb.shape[2] * rgb.shape[3]
        mean = torch.div(gray.sum((2, 3), keepdim=True) * 2 + count,
                         count * 2, rounding_mode="trunc").float()
        return (mean + (sharpened.float() - mean) * 1.4).clamp(0, 255).to(torch.int64)

    def forward(self, normalized):
        rgb = torch.round((normalized * self.std + self.mean) * 255).clamp(0, 255)
        enhanced = self.enhance(rgb).float() / 255
        return (enhanced - self.mean) / self.std
