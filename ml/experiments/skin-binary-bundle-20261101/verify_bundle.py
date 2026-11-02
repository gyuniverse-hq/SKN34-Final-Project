"""Check exported weights and standalone inference without reusing held-out data."""

import hashlib
import importlib.util
import json
import tempfile
from pathlib import Path

import torch
from PIL import Image
from torch import nn
from torchvision.models import mobilenet_v3_large


def verify_bundle(bundle):
    bundle = Path(bundle).resolve()
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    plan = json.loads((bundle / "bundle-plan.json").read_text(encoding="utf-8"))
    spec = importlib.util.spec_from_file_location(
        "standalone_skin_binary_bundle", bundle / "predict.py"
    )
    if spec is None or spec.loader is None:
        raise ImportError("Cannot import standalone predictor")
    predictor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(predictor)
    torch.set_num_threads(4)
    results = {}
    with tempfile.TemporaryDirectory(prefix="skin-binary-export-") as temporary:
        image = Path(temporary) / "synthetic-sanity-input.png"
        Image.new("RGB", (256, 256), (139, 104, 86)).save(image)
        for task, record in manifest["models"].items():
            path = (bundle / record["file"]).resolve(strict=True)
            if not path.is_relative_to(bundle):
                raise ValueError("Exported weight path escapes the bundle")
            if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
                raise ValueError(f"Export hash differs: {task}")
            state = torch.load(path, map_location="cpu", weights_only=True)["model_state"]
            original = torch.load(
                plan["models"][task]["source"], map_location="cpu", weights_only=True
            )["model_state"]
            if state.keys() != original.keys() or any(
                not torch.equal(state[key], original[key]) for key in state
            ):
                raise ValueError(f"Export state differs from the selected model: {task}")
            model = mobilenet_v3_large(weights=None)
            outputs = 3 if task == "skin_type_roi" else 1
            model.classifier[-1] = nn.Linear(model.classifier[-1].in_features, outputs)
            model.load_state_dict(original, strict=True)
            model.eval()
            with torch.inference_mode():
                logits = model(predictor.prepare(image).unsqueeze(0)).float()
            if logits.shape != (1, outputs) or not torch.isfinite(logits).all():
                raise ValueError(f"Invalid export topology/output: {task}")
            result = predictor.predict(task, [image])
            if outputs == 1:
                expected = logits.sigmoid().reshape(-1)[0].item()
                error = abs(expected - result["probability_caution"])
                if result["label"] != int(expected >= 0.5):
                    raise ValueError(f"Wrong binary decoding: {task}")
            else:
                expected = logits.softmax(1)[0]
                error = float((expected - torch.tensor(result["scores"])).abs().max())
            if error > 1e-6:
                raise ValueError(f"Standalone inference differs: {task}: {error}")
            results[task] = dict(
                sha256_verified=True,
                tensors_identical=True,
                output_shape=list(logits.shape),
                max_absolute_error=error,
            )
    report = dict(
        status="passed", input="generated constant RGB sanity image; no Test data", models=results
    )
    (bundle / "EXPORT_VERIFICATION.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report
