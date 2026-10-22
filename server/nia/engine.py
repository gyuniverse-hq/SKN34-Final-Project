"""Strict, read-only checkpoint loading and synchronized inference."""

import hashlib
import importlib.metadata
import time
from pathlib import Path

import torch
from torchvision.models import resnet50

from .catalog import SOURCE_COMMIT, TASKS, validate_model
from .imaging import prepare
from .metrics import timing


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Engine:
    def __init__(self, config):
        self.config = validate_model(config)
        self.model = None
        self.metadata = None
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    def sync(self):
        if self.device.type == "cuda":
            torch.cuda.synchronize(self.device)

    def load(self):
        if self.model is not None:
            return self.metadata
        start = time.perf_counter()
        path = Path(self.config["checkpoint"]).resolve(strict=True)
        digest = sha256(path)
        if digest != self.config["sha256"].lower():
            raise ValueError("Checkpoint hash mismatch; inference blocked")
        # Never fall back to pickle execution. Older numpy metadata may need an audited conversion.
        checkpoint = torch.load(path, map_location="cpu", weights_only=True)
        if not isinstance(checkpoint, dict) or not isinstance(checkpoint.get("model_state"), dict):
            raise ValueError("Expected official checkpoint dictionary with model_state")
        state = checkpoint["model_state"]
        outputs = TASKS[self.config["task"]][1]
        if "fc.weight" not in state or tuple(state["fc.weight"].shape) != (outputs, 2048):
            raise ValueError("ResNet-50 output head does not match configured labels")
        if any(not isinstance(t, torch.Tensor) or not torch.isfinite(t).all() for t in state.values()):
            raise ValueError("Invalid or non-finite checkpoint tensor")
        model = resnet50(weights=None, num_classes=outputs)
        model.load_state_dict(state, strict=True)
        self.sync()
        before = torch.cuda.memory_allocated(self.device) if self.device.type == "cuda" else None
        model = model.to(self.device).eval().requires_grad_(False)
        self.sync()
        resident = torch.cuda.memory_allocated(self.device) - before if before is not None else None
        loaded_ms = (time.perf_counter() - start) * 1000
        # Warm-up uses a dummy tensor only for timing preparation, never for a reported prediction.
        warm_start = time.perf_counter()
        with torch.inference_mode():
            warm = torch.zeros(1, 3, 256, 256, device=self.device)
            for _ in range(3):
                model(warm)
            self.sync()
        self.metadata = dict(id=self.config["id"], task=self.config["task"],
                             checkpoint=str(path), sha256=digest, source=self.config["source"],
                             label_evidence=self.config["label_evidence"],
                             architecture="torchvision/resnet50", outputs=outputs, resolution=256,
                             grades=self.config.get("grades"), areas=self.config["areas"],
                             unit=self.config.get("unit"),
                             device=str(self.device), gpu=torch.cuda.get_device_name() if resident is not None else None,
                             gpu_resident_bytes=resident, load_ms=loaded_ms,
                             warmup_ms=(time.perf_counter() - warm_start) * 1000,
                             source_commit=SOURCE_COMMIT,
                             libraries={p: importlib.metadata.version(p) for p in
                                        ("torch", "torchvision", "numpy", "Pillow", "opencv-python-headless")})
        self.model = model
        return self.metadata

    def predict(self, raw, area, bbox=None, precropped=False, repeats=1, preview=True):
        start = time.perf_counter()
        metadata = self.load()
        if area not in self.config["areas"]:
            raise ValueError("Area not verified for this checkpoint")
        if type(repeats) is not int or not 1 <= repeats <= 100:
            raise ValueError("repeats must be between 1 and 100")
        prep_start = time.perf_counter()
        tensor, preprocessing = prepare(raw, bbox, self.config["areas"][area][0], precropped, preview)
        preprocessing["configured_faceparts"] = self.config["areas"][area]
        tensor = tensor.to(self.device)
        self.sync()
        prep_ms = (time.perf_counter() - prep_start) * 1000
        if self.device.type == "cuda":
            torch.cuda.reset_peak_memory_stats(self.device)
        samples = []
        with torch.inference_mode():
            for _ in range(repeats):
                self.sync()
                tick = time.perf_counter()
                output = self.model(tensor)
                self.sync()
                samples.append((time.perf_counter() - tick) * 1000)
            if not torch.isfinite(output).all():
                raise ValueError("Non-finite model output")
            mode, _, multiplier, _ = TASKS[self.config["task"]]
            if mode == "class":
                probabilities = output.softmax(dim=1)[0].cpu().tolist()
                prediction = dict(grade=int(output.argmax(dim=1).item()), probabilities=probabilities)
            else:
                prediction = dict(value=output.item() * multiplier, unit=self.config["unit"],
                                  normalized_value=output.item(), multiplier=multiplier)
        return dict(model=metadata, area=area, mode=mode, prediction=prediction,
                    preprocessing=preprocessing, preprocessing_ms=prep_ms, inference=timing(samples),
                    server_ms=(time.perf_counter() - start) * 1000,
                    gpu_peak_process_bytes=torch.cuda.max_memory_allocated(self.device)
                    if self.device.type == "cuda" else None)
