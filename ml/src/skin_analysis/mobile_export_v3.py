"""Export only the four skin-analysis-v3 models with embedded ROI enhancement."""

import argparse
import hashlib
import json
import math
import shutil
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np
import onnx
import onnxruntime as ort
import torch
from PIL import Image, ImageEnhance, ImageFilter
from torch import nn
from torchvision.models import mobilenet_v3_large

from .mobile_enhancement import RoiEnhancement
from .mobile_export import OUTPUT_ROOT, ROOT, digest, fixtures

DEFAULT_BUNDLE = ROOT / "ml/runs/skin-analysis-v3/bundle-four-models-20261030"
CLASSES = ["dry", "balanced", "oily"]


def decode_grade(value, maximum):
    score = torch.sigmoid(torch.tensor(float(value))).item() * maximum
    return min(maximum, max(0, math.floor(score + .5)))


def load_research_model(bundle, task, record):
    path = (bundle / record["file"]).resolve(strict=True)
    if not path.is_relative_to(bundle) or digest(path) != record["sha256"]:
        raise ValueError(f"Invalid v3 checkpoint: {task}")
    if record["architecture"] != "mobilenet_v3_large":
        raise ValueError(f"Unsupported v3 architecture: {task}")
    outputs = 3 if task == "skin_type_roi" else 1
    if task == "skin_type_roi":
        if record["classes"] != ["건성", "중성", "지성"]:
            raise ValueError("Skin type class order changed")
    elif record["max_grade"] != (6 if task == "wrinkle" else 5):
        raise ValueError("Unexpected grade range")
    model = mobilenet_v3_large(weights=None)
    model.classifier[-1] = nn.Linear(model.classifier[-1].in_features, outputs)
    model.load_state_dict(torch.load(path, map_location="cpu", weights_only=True)["model_state"],
                          strict=True)
    if any(not torch.isfinite(value).all() for value in model.state_dict().values()):
        raise ValueError("Non-finite v3 checkpoint")
    return model.eval().requires_grad_(False)


def reference_input(values):
    enhancement = RoiEnhancement()
    rgb = torch.round((torch.from_numpy(values) * enhancement.std + enhancement.mean) * 255)
    image = Image.fromarray(rgb[0].permute(1, 2, 0).numpy().astype(np.uint8))
    image = ImageEnhance.Contrast(image.filter(
        ImageFilter.UnsharpMask(radius=1, percent=75, threshold=0))).enhance(1.4)
    tensor = torch.from_numpy(np.array(image)).permute(2, 0, 1).unsqueeze(0).float() / 255
    return (tensor - enhancement.mean) / enhancement.std


def export(bundle=DEFAULT_BUNDLE):
    bundle = Path(bundle).resolve(strict=True)
    source = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    tasks = ("pore", "pigmentation", "wrinkle", "skin_type_roi")
    if source["schema"] != "skin-research-four-models-v1" or set(source["models"]) != set(tasks):
        raise ValueError("Incomplete v3 research bundle")
    if source["grade_preprocessing"] != (
        "official square ROI JPEG 256 RGB, unsharp radius 1 percent 75 threshold 0, "
        "contrast 1.4, ImageNet normalize"
    ):
        raise ValueError("Unsupported v3 ROI preprocessing")
    fingerprint = ((bundle / "manifest.json").read_bytes()
                   + Path(__file__).read_bytes()
                   + Path(__file__).with_name("mobile_enhancement.py").read_bytes())
    version = hashlib.sha256(fingerprint).hexdigest()
    output = OUTPUT_ROOT / version
    # Always verify the source checkpoints, even when reusing an immutable export.
    models = {task: load_research_model(bundle, task, source["models"][task]) for task in tasks}
    if output.exists():
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        if any(digest(output / name) != sha for name, sha in manifest["assets"].items()):
            raise ValueError("Corrupt immutable v3 export")
        return output
    torch.set_num_threads(2)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="v3-export-", dir=OUTPUT_ROOT) as temporary:
        stage = Path(temporary) / "bundle"
        stage.mkdir()
        fixture_records = fixtures(stage)
        shutil.copyfile(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml",
                        stage / "face.xml")
        shutil.copyfile(ROOT / "docs/licenses/Pillow.txt", stage / "Pillow-LICENSE.txt")
        records = []
        for task, network in models.items():
            print(f"Exporting v3 {task}", file=sys.stderr, flush=True)
            model = nn.Sequential(RoiEnhancement(), network).eval().requires_grad_(False)
            path = stage / f"{task}.onnx"
            values = np.fromfile(stage / "downsample.f32", dtype="<f4").reshape(1, 3, 256, 256)
            with torch.inference_mode():
                torch.onnx.export(model, torch.from_numpy(values), path, input_names=["image"],
                                  output_names=["logits"], opset_version=17, dynamo=False,
                                  external_data=False)
            onnx.checker.check_model(str(path))
            options = ort.SessionOptions()
            options.intra_op_num_threads = 2
            session = ort.InferenceSession(str(path), options, providers=["CPUExecutionProvider"])
            errors = []
            for fixture in fixture_records:
                array = np.fromfile(stage / fixture["tensor"], dtype="<f4").reshape(1, 3, 256, 256)
                with torch.inference_mode():
                    reference = network(reference_input(array)).numpy()
                actual = session.run(["logits"], {"image": array})[0]
                np.testing.assert_allclose(actual, reference, rtol=1e-3, atol=1e-4)
                if task == "skin_type_roi":
                    assert actual.argmax() == reference.argmax(), "Skin type decision changed"
                else:
                    maximum = source["models"][task]["max_grade"]
                    assert (decode_grade(actual.item(), maximum)
                            == decode_grade(reference.item(), maximum)), "Grade changed"
                errors.append(float(np.max(np.abs(actual - reference))))
            with torch.inference_mode():
                expected = network(reference_input(values)).numpy()[0].tolist()
            record = source["models"][task]
            records.append(dict(indicator="skinType" if task == "skin_type_roi" else task,
                                file=path.name, sha256=digest(path), sourceSha256=record["sha256"],
                                input="image", output="logits", inputShape=[1, 3, 256, 256],
                                outputs=3 if task == "skin_type_roi" else 1,
                                decoder=("mean_softmax" if task == "skin_type_roi"
                                         else "sigmoid_grade"),
                                maxGrade=record.get("max_grade"),
                                classes=CLASSES if task == "skin_type_roi" else None,
                                fixture="downsample.f32", expectedLogits=expected,
                                maxExportAbsoluteError=max(errors),
                                roiEnhancement="pillow-unsharp1-75-contrast1.4-embedded"))
        manifest = dict(
            schema="skin-analysis-assets-v3", bundleVersion=version, precision="float32",
            opset=17, preprocessing="skin-preprocessing-v3", pythonRuntime=ort.__version__,
            androidRuntime="1.22.0", roiMethod="opencv_haar_facebox_proportions_v1",
            researchManifestSha256=digest(bundle / "manifest.json"), models=records,
            assets={file.name: digest(file) for file in stage.iterdir() if file.is_file()})
        (stage / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        stage.replace(output)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    print(export(parser.parse_args().bundle))


if __name__ == "__main__":
    main()
