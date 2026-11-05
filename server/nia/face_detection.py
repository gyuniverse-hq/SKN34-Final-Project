"""Server-only YuNet localization; reuse the existing NIA geometric ROI contract."""

import argparse
import hashlib
import urllib.request
from pathlib import Path

import cv2

from .imaging import decode
from .profile import regions_from_face

ROOT = Path(__file__).absolute().parents[2]
DEFAULT_MODEL = ROOT / "ml/runs/face-detection/face_detection_yunet_2023mar.onnx"
MODEL_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
MODEL_URL = (
    "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/"
    "models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
)
ROI_METHOD = "opencv_yunet_facebox_proportions_v1"


class YuNetRegions:
    """Construct once, call sequentially; face localization stays on the CPU."""

    def __init__(self, model_path=DEFAULT_MODEL):
        path = Path(model_path)
        if hashlib.sha256(path.read_bytes()).hexdigest() != MODEL_SHA256:
            raise ValueError("YuNet model SHA-256 mismatch")
        self.detector = cv2.FaceDetectorYN.create(
            str(path),
            "",
            (320, 320),
            0.9,
            0.3,
            5000,
            cv2.dnn.DNN_BACKEND_OPENCV,
            cv2.dnn.DNN_TARGET_CPU,
        )

    def __call__(self, raw):
        image = decode(raw)
        height, width = image.shape[:2]
        scale = min(1.0, 900 / max(height, width))
        small = cv2.resize(image, (round(width * scale), round(height * scale)))
        self.detector.setInputSize((small.shape[1], small.shape[0]))
        _, faces = self.detector.detect(small)
        if faces is None or len(faces) == 0:
            raise ValueError("No frontal face detected. Use a clear, upright photo with one face.")
        if len(faces) != 1:
            raise ValueError("Multiple faces detected. Use a photo containing only one face.")
        face = [float(value) / scale for value in faces[0][:4]]
        return regions_from_face(width, height, face, method=ROI_METHOD)


def download_model(output=DEFAULT_MODEL):
    """Explicit setup command only; a running API never downloads weights."""
    path = Path(output)
    if path.is_file():
        if hashlib.sha256(path.read_bytes()).hexdigest() != MODEL_SHA256:
            raise ValueError("Existing YuNet model SHA-256 mismatch; not overwriting")
        return path
    with urllib.request.urlopen(MODEL_URL, timeout=30) as response:
        raw = response.read(1024 * 1024)
    if hashlib.sha256(raw).hexdigest() != MODEL_SHA256:
        raise ValueError("Downloaded YuNet model SHA-256 mismatch")
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents replacing an existing artifact.
    with path.open("xb") as target:
        target.write(raw)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_MODEL)
    args = parser.parse_args()
    print(download_model(args.output))


if __name__ == "__main__":
    main()
