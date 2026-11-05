"""Export the selected local bundle to immutable, numerically verified mobile assets."""

import argparse
import hashlib
import io
import json
import shutil
import tempfile
from pathlib import Path

import cv2
import numpy as np
import onnx
import onnxruntime as ort
import torch
from PIL import Image
from server.nia.imaging import prepare
from server.nia.recommendation import bundle_config
from torchvision.models import resnet50

from .acne.data import prepare_image
from .acne.model import load_bundle

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BUNDLE = ROOT / "ml/runs/nia-smartphone-sam-seed-42/recommendation-bundle"
OUTPUT_ROOT = ROOT / "ml/runs/skin-mobile"


def digest(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def fixtures(output):
    records = []
    for name, width, height, bbox in (
        ("identity", 256, 256, None),
        ("downsample", 773, 517, None),
        ("upsample", 117, 151, None),
        ("crop", 513, 397, [43, 37, 311, 283]),
    ):
        y, x = np.indices((height, width))
        rgb = np.stack(((x * 7 + y * 3) % 256, (x * 2 + y * 11) % 256,
                        ((x // 9 + y // 7) % 2) * 255), axis=-1).astype(np.uint8)
        buffer = io.BytesIO()
        Image.fromarray(rgb).save(buffer, format="PNG")
        raw = buffer.getvalue()
        (output / f"{name}.png").write_bytes(raw)
        tensor = prepare(raw, bbox, 5, False, False)[0] if bbox else prepare_image(raw).unsqueeze(0)
        tensor.numpy().astype("<f4").tofile(output / f"{name}.f32")
        records.append(dict(image=f"{name}.png", tensor=f"{name}.f32", bbox=bbox,
                            maxAbsoluteError=1e-5))
    (output / "fixtures.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    return records


def export(bundle=DEFAULT_BUNDLE):
    bundle = Path(bundle).resolve(strict=True)
    config = bundle_config(bundle)  # Contract, path containment and original hashes.
    bundle_version = digest(bundle / "manifest.json")
    output = OUTPUT_ROOT / bundle_version
    if output.exists():
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        if any(digest(output / name) != sha for name, sha in manifest["assets"].items()):
            raise ValueError("Existing immutable export is incomplete or corrupted")
        return output
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(2)
    with tempfile.TemporaryDirectory(prefix="export-", dir=OUTPUT_ROOT) as temporary:
        stage = Path(temporary) / "bundle"
        stage.mkdir()
        fixture_records = fixtures(stage)
        models = []
        records = {m["task"].split("/")[1]: m for m in config["models"]}
        records["acne"] = config["acne"]
        for indicator in ("acne", "pore", "pigmentation", "wrinkle"):
            record = records[indicator]
            if indicator == "acne":
                model, checkpoint = load_bundle(record["checkpoint"])
                threshold = checkpoint["threshold"]
                outputs = 1
            else:
                outputs = 7 if indicator == "wrinkle" else 6
                model = resnet50(weights=None, num_classes=outputs).eval().requires_grad_(False)
                checkpoint = torch.load(record["checkpoint"], map_location="cpu", weights_only=True)
                model.load_state_dict(checkpoint["model_state"], strict=True)
                threshold = None
            model.eval().requires_grad_(False)
            path = stage / f"{indicator}.onnx"
            tensor = torch.from_numpy(
                np.fromfile(stage / "downsample.f32", dtype="<f4").reshape(1, 3, 256, 256)
            )
            with torch.inference_mode():
                torch.onnx.export(model, tensor, path,
                                  input_names=["image"], output_names=["logits"],
                                  opset_version=17, dynamo=False, external_data=False)
            onnx.checker.check_model(str(path))
            session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
            errors = []
            for fixture in fixture_records:
                array = np.fromfile(stage / fixture["tensor"], dtype="<f4").reshape(1, 3, 256, 256)
                with torch.inference_mode():
                    expected = model(torch.from_numpy(array)).numpy()
                actual = session.run(["logits"], {"image": array})[0]
                np.testing.assert_allclose(actual, expected, rtol=1e-3, atol=1e-4)
                if indicator == "acne":
                    expected_label = int(
                        torch.sigmoid(torch.tensor(expected.item())).item() >= threshold)
                    actual_label = int(
                        torch.sigmoid(torch.tensor(actual.item())).item() >= threshold)
                    assert actual_label == expected_label, "Acne threshold decision changed"
                else:
                    assert actual.argmax() == expected.argmax(), "Grade decision changed"
                errors.append(float(np.max(np.abs(actual - expected))))
            expected = session.run(["logits"], {"image": tensor.numpy()})[0][0].tolist()
            models.append(dict(indicator=indicator, file=path.name, sha256=digest(path),
                               sourceSha256=record["sha256"], input="image", output="logits",
                               inputShape=[1, 3, 256, 256], outputs=outputs, threshold=threshold,
                               fixture="downsample.f32", expectedLogits=expected,
                               maxExportAbsoluteError=max(errors)))
            del model, checkpoint, session
        cascade = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
        shutil.copyfile(cascade, stage / "face.xml")
        # Include the license of the OpenCV cascade distributed with the model.
        manifest = dict(schema="skin-analysis-assets-v1", bundleVersion=bundle_version,
                        precision="float32", opset=17, pythonRuntime=ort.__version__,
                        androidRuntime="1.22.0", preprocessing="skin-preprocessing-v1",
                        roiMethod="opencv_haar_facebox_proportions_v1", models=models,
                        assets={f.name: digest(f) for f in stage.iterdir() if f.is_file()})
        (stage / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        # Publish the complete directory atomically, never a partial manifest.
        stage.replace(output)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    args = parser.parse_args()
    print(export(args.bundle))


if __name__ == "__main__":
    main()
