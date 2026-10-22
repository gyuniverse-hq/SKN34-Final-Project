"""Strict inference bundle loading with an independent failure boundary."""

import time
from pathlib import Path

import torch

from ml.src.skin_analysis.acne.common import file_hash
from ml.src.skin_analysis.acne.data import prepare_image
from ml.src.skin_analysis.acne.model import load_bundle


class AcneEngine:
    def __init__(self, config, device=None):
        self.config = config
        self.device = device or torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = None
        self.bundle = None

    def sync(self):
        if self.device.type == "cuda":
            torch.cuda.synchronize(self.device)

    def load(self):
        if self.model is None:
            if (not isinstance(self.config, dict)
                    or not isinstance(self.config.get("checkpoint"), str)
                    or not isinstance(self.config.get("sha256"), str)
                    or len(self.config["sha256"]) != 64):
                raise ValueError("Acne checkpoint path and SHA-256 are required")
            path = Path(self.config["checkpoint"]).resolve(strict=True)
            if file_hash(path) != self.config["sha256"]:
                raise ValueError("Acne checkpoint hash mismatch")
            model, bundle = load_bundle(path)
            if (bundle.get("validation_status")
                    != "synthetic_only_person_independence_unverified"):
                raise ValueError("Expected an explicitly qualified acne research bundle")
            self.model = model.to(self.device).eval()
            self.bundle = bundle

    def predict(self, raw):
        started = time.perf_counter()
        self.load()
        self.sync()
        prep_start = time.perf_counter()
        image = prepare_image(raw).unsqueeze(0).to(self.device)
        self.sync()
        preprocessing_ms = (time.perf_counter() - prep_start) * 1000
        tick = time.perf_counter()
        with torch.inference_mode():
            output = self.model(image)
            if not torch.isfinite(output).all():
                raise ValueError("Non-finite acne prediction")
            score = float(output.float().sigmoid().item())
        self.sync()
        return {
            "status": "predicted", "label": int(score >= self.bundle["threshold"]),
            "score": score, "score_type": "sigmoid_uncalibrated",
            "threshold": self.bundle["threshold"], "model_sha256": self.config["sha256"],
            "validation_status": self.bundle["validation_status"],
            "training_domain": "synthetic_frontal_normal_vs_acne_only",
            "other_diseases_supported": False, "diagnosis": False,
            "preprocessing": self.bundle["preprocessing"], "preprocessing_ms": preprocessing_ms,
            "inference_ms": (time.perf_counter() - tick) * 1000,
            "server_ms": (time.perf_counter() - started) * 1000,
        }
