"""OpenCV crop -> 256 JPEG -> RGB -> PIL resize -> ImageNet normalize, as upstream."""

import base64
import io
import math

import cv2
import numpy as np
from PIL import Image
from torchvision import transforms

MAX_PIXELS = 30_000_000


def decode(raw):
    with Image.open(io.BytesIO(raw)) as header:
        if header.format not in ("JPEG", "PNG") or header.width * header.height > MAX_PIXELS:
            raise ValueError("Only JPEG/PNG up to 30 megapixels are supported")
    image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Image decoding failed")
    return image


def crop_bounds(bbox, width, height, facepart):
    if not isinstance(bbox, list) or len(bbox) != 4:
        raise ValueError("Explicit ROI [x1,y1,x2,y2] is required")
    if any(type(v) not in (float, int) or not math.isfinite(v) for v in bbox):
        raise ValueError("ROI coordinates must be finite numbers")
    x1, y1, x2, y2 = map(int, bbox)
    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        raise ValueError("ROI must be inside the decoded image")
    if facepart == 0:
        return [0, 0, width, height]
    cx, cy = int((x1 + x2) / 2), int((y1 + y2) / 2)
    half = int(max(x2 - x1, y2 - y1) / 2)
    if half < 1:
        raise ValueError("ROI too small")
    return [max(cx - half, 0), max(cy - half, 0), min(cx + half, width), min(cy + half, height)]


def prepare(raw, bbox=None, facepart=None, precropped=False, include_preview=True):
    image = decode(raw)
    height, width = image.shape[:2]
    bounds = None
    if not precropped:
        bounds = crop_bounds(bbox, width, height, facepart)
        x1, y1, x2, y2 = bounds
        image = cv2.resize(image[y1:y2, x1:x2], (256, 256), interpolation=cv2.INTER_LINEAR)
        # img_crop.py writes .jpg with OpenCV's default quality, then data_loader.py reads it.
        ok, encoded = cv2.imencode(".jpg", image)
        if not ok:
            raise ValueError("Crop JPEG encoding failed")
        image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    elif width != 256 or height != 256:
        raise ValueError("Official pre-cropped images must be 256 x 256")
    rgb = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    resized = transforms.Resize((256, 256), antialias=True)(rgb)
    tensor = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize([.485, .456, .406], [.229, .224, .225]),
    ])(resized).unsqueeze(0)
    info = dict(original_size=[width, height], requested_bbox=bbox, crop=bounds,
                input_size=[256, 256],
                method="official_precropped" if precropped else "official_square_jpeg")
    if include_preview:
        buffer = io.BytesIO()
        resized.save(buffer, format="PNG")
        info["preview"] = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
    return tensor, info
