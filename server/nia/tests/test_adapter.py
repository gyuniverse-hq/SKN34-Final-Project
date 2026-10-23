import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
import torch
from torchvision import transforms

from server.nia.catalog import TASKS, validate_model
from server.nia.dataset import inside, prepare_dataset
from server.nia.engine import Engine
from server.nia.imaging import crop_bounds, prepare
from server.nia.service import Service


def config():
    return dict(id="fixture", task="class/wrinkle", checkpoint="missing.bin", sha256="0" * 64,
                architecture="resnet50", resolution=256,
                source="unit test fixture, not a real NIA checkpoint", label_evidence="unit test ROI",
                grades=list(range(7)), areas={"forehead_wrinkle": 1})


class AdapterTests(unittest.TestCase):
    def test_definitions_no_acne_or_skin_tone(self):
        self.assertEqual(TASKS["class/wrinkle"][1], 7)
        self.assertEqual([TASKS[f"regression/{k}"][2] for k in
                          ("moisture", "elasticity_R2", "wrinkle_Ra", "pigmentation", "pore")],
                         [100, 1, 50, 350, 2600])
        with self.assertRaises(ValueError):
            validate_model({**config(), "task": "class/acne"})
        with self.assertRaises(ValueError):
            validate_model({**config(), "grades": list(range(6))})

    def test_crop_rounding_and_edge_clipping_matches_upstream(self):
        self.assertEqual(crop_bounds([0, 0, 5, 9], 20, 20, 1), [0, 0, 6, 8])
        self.assertEqual(crop_bounds([1, 1, 5, 9], 20, 20, 0), [0, 0, 20, 20])
        for bbox in (None, [-1, 0, 5, 9], [0, 0, 0, 0], [0, 0, float("nan"), 1]):
            with self.assertRaises(ValueError):
                crop_bounds(bbox, 20, 20, 1)

    def test_full_preprocessing_matches_official_disk_roundtrip(self):
        image = np.random.default_rng(7).integers(0, 256, (81, 93, 3), dtype=np.uint8)
        _, encoded = cv2.imencode(".png", image)
        actual, info = prepare(encoded.tobytes(), [3, 5, 36, 68], 1)
        # Independently reproduce img_crop.py and data_loader.py, including JPEG file IO.
        bbox = [3, 5, 36, 68]
        center_x, center_y = int((bbox[0] + bbox[2]) / 2), int((bbox[1] + bbox[3]) / 2)
        half = int(max(bbox[3] - bbox[1], bbox[2] - bbox[0]) / 2)
        cropped = image[max(center_y - half, 0):min(center_y + half, 81),
                        max(center_x - half, 0):min(center_x + half, 93)]
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "crop.jpg")
            cv2.imwrite(path, cv2.resize(cropped, (256, 256)))
            rgb = Image.fromarray(cv2.cvtColor(cv2.imread(path), cv2.COLOR_BGR2RGB))
            expected = transforms.Compose([
                transforms.Resize((256, 256), antialias=True), transforms.ToTensor(),
                transforms.Normalize([.485, .456, .406], [.229, .224, .225]),
            ])(rgb).unsqueeze(0)
        torch.testing.assert_close(actual, expected, rtol=0, atol=0)
        self.assertEqual(info["input_size"], [256, 256])
        self.assertTrue(info["preview"].startswith("data:image/png;base64,"))

    def test_missing_checkpoint_cannot_predict(self):
        with self.assertRaises(FileNotFoundError):
            Engine(config()).load()

    def test_hash_and_output_mismatch_are_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.bin"
            path.write_bytes(b"not weights")
            with self.assertRaisesRegex(ValueError, "hash mismatch"), patch("server.nia.engine.torch.load") as load:
                Engine({**config(), "checkpoint": str(path)}).load()
            load.assert_not_called()
            with patch("server.nia.engine.sha256", return_value="0" * 64), patch(
                "server.nia.engine.torch.load", return_value={"model_state": {"fc.weight": torch.zeros(6, 2048)}}
            ) as load, self.assertRaisesRegex(ValueError, "output head"):
                Engine({**config(), "checkpoint": str(path)}).load()
            self.assertTrue(load.call_args.kwargs["weights_only"])

    def test_missing_config_status_has_no_predictions(self):
        service = Service("not-a-real-config.json")
        self.addCleanup(service.worker.shutdown)
        self.assertEqual(service.status()["models"], [])
        self.assertFalse(service.status()["dataset_configured"])
        with self.assertRaises(ValueError):
            service.infer({"roi_confirmed": False})

    def test_strict_loading_rejects_missing_backbone(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.bin"
            path.write_bytes(b"fixture only")
            with patch("server.nia.engine.sha256", return_value="0" * 64), patch(
                "server.nia.engine.torch.load", return_value={"model_state": {"fc.weight": torch.zeros(7, 2048)}}
            ), self.assertRaisesRegex(RuntimeError, "Missing key"):
                Engine({**config(), "checkpoint": str(path)}).load()

    def test_prediction_modes_and_no_preview_with_test_double(self):
        # A fixed-output test double verifies adapter semantics, never used by the running service.
        class Fixed(torch.nn.Module):
            def __init__(self, output):
                super().__init__()
                self.output = output

            def forward(self, tensor):
                self.assert_inference = torch.is_inference_mode_enabled()
                return self.output

        _, encoded = cv2.imencode(".png", np.zeros((256, 256, 3), dtype=np.uint8))
        engine = Engine(config())
        engine.device = torch.device("cpu")
        engine.model = Fixed(torch.tensor([[0., 0., 0., 3., 0., 0., 0.]])).eval()
        engine.metadata = {"unit_test_only": True}
        result = engine.predict(encoded.tobytes(), "forehead_wrinkle", precropped=True, preview=False)
        self.assertEqual(result["prediction"]["grade"], 3)
        self.assertAlmostEqual(sum(result["prediction"]["probabilities"]), 1, places=6)
        self.assertNotIn("preview", result["preprocessing"])
        self.assertNotIn("accuracy", result)
        self.assertTrue(engine.model.assert_inference)
        engine = Engine({**config(), "task": "regression/wrinkle_Ra", "unit": "evidenced test unit",
                         "areas": {"perocular_wrinkle_Ra": [3, 4]}})
        engine.device = torch.device("cpu")
        engine.model = Fixed(torch.tensor([[.5]])).eval()
        engine.metadata = {"unit_test_only": True}
        result = engine.predict(encoded.tobytes(), "perocular_wrinkle_Ra", precropped=True, preview=False)
        self.assertEqual(result["prediction"]["value"], 25)
        self.assertNotIn("grade", result["prediction"])

    def test_official_labels_and_person_leakage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            descriptor = "Sub_0001_Equ_1_Angle_0_Area_1"
            split = {"forehead_wrinkle": [descriptor]}
            for name in ("train", "val", "test"):
                (root / f"{name}.json").write_text(json.dumps(split), encoding="utf-8")
            (root / "label/1/0001").mkdir(parents=True)
            (root / "cropped_img/1/0001").mkdir(parents=True)
            label_path = root / "label/1/0001/0001_1_0_1.json"
            label = {"images": {"facepart": 1, "bbox": [0, 0, 10, 10]},
                     "annotations": {"forehead_wrinkle": 3}, "info": {"filename": "0001_1_0.jpg"}}
            label_path.write_text(json.dumps(label), encoding="utf-8")
            cv2.imwrite(str(root / "cropped_img/1/0001/0001_1_0_1.jpg"), np.zeros((256, 256, 3), dtype=np.uint8))
            request = dict(dataset_root=str(root), test_split="test.json", train_split="train.json", val_split="val.json")
            records, audit = prepare_dataset(request, config(), [str(root)])
            self.assertEqual(records[0]["truth"], 3)
            self.assertEqual(records[0]["device"], "DSLR")
            self.assertEqual(audit["leakage"]["status"], "overlap")
            self.assertEqual(audit["leakage"]["overlap_person_ids"], ["0001"])
            request.pop("train_split"); request.pop("val_split")
            self.assertEqual(prepare_dataset(request, config(), [str(root)])[1]["leakage"]["status"], "unverified")
            label_request = dict(dataset_root=str(root), labels_directory="label")
            label_records, label_audit = prepare_dataset(label_request, config(), [str(root)])
            self.assertEqual(label_records[0]["truth"], 3)
            self.assertEqual(label_audit["selection_source"], "original_annotations_without_official_test_split")
            self.assertEqual(label_audit["leakage"]["status"], "unverified")
            label["annotations"]["forehead_wrinkle_extra"] = 2
            label_path.write_text(json.dumps(label), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "ambiguous"):
                prepare_dataset(request, config(), [str(root)])

    def test_dataset_path_cannot_escape_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "allowed").mkdir()
            (root / "secret.json").write_text("{}")
            with self.assertRaises(ValueError):
                inside(root / "allowed", "../secret.json")

    def test_retrained_phone_model_cannot_report_original_split_as_its_holdout(self):
        with tempfile.TemporaryDirectory() as directory:
            service = Service(Path(directory) / "missing-config.json")
            self.addCleanup(service.worker.shutdown)
            service.engines["fixture"] = Engine({**config(), "training_device": "smartphone"})
            with self.assertRaisesRegex(ValueError, "new person split"):
                service.submit_evaluation({"model_id": "fixture"})
            self.assertEqual(service.jobs, {})

    def test_evaluation_report_and_exports_with_test_double(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            descriptor = "Sub_0001_Equ_1_Angle_0_Area_1"
            (root / "test.json").write_text(json.dumps({"forehead_wrinkle": [descriptor]}))
            (root / "label/1/0001").mkdir(parents=True)
            (root / "cropped_img/1/0001").mkdir(parents=True)
            (root / "label/1/0001/0001_1_0_1.json").write_text(json.dumps({
                "images": {"facepart": 1, "bbox": [0, 0, 10, 10]},
                "annotations": {"forehead_wrinkle": 3},
                "info": {"filename": "0001_1_0.jpg"},
            }))
            cv2.imwrite(str(root / "cropped_img/1/0001/0001_1_0_1.jpg"), np.zeros((256, 256, 3), dtype=np.uint8))
            (root / "meta.csv").write_text(f"sample_id,population\n{descriptor},=unit-test\n")
            service = Service(root / "missing-config.json")
            self.addCleanup(service.worker.shutdown)
            service.config = {"dataset_roots": [str(root)], "metadata_evidence": "unit test fixture only"}
            engine = Engine(config())
            class Fixed(torch.nn.Module):
                def forward(self, tensor):
                    return torch.tensor([[0., 0., 0., 3., 0., 0., 0.]])
            engine.device = torch.device("cpu")
            engine.model = Fixed().eval()
            engine.metadata = dict(id="fixture", sha256="0" * 64, task="class/wrinkle", device="cpu")
            service.engines["fixture"] = engine
            job = {"id": "unit-test", "status": "queued"}
            service.jobs[job["id"]] = job
            request = dict(model_id="fixture", dataset_root=str(root), test_split="test.json", metadata_csv="meta.csv")
            service.run_job(job, engine, request)
            self.assertEqual(job["status"], "completed", job.get("error"))
            self.assertEqual(job["report"]["metrics"]["accuracy"], 1)
            self.assertEqual(job["report"]["dataset"]["leakage"]["status"], "unverified")
            self.assertEqual(job["report"]["groups"]["device"]["DSLR"]["n"], 1)
            self.assertNotIn("preview", job["report"]["samples"][0])
            self.assertNotIn("records", service.dispatch("job", {}, {"id": [job["id"]]}))
            csv = service.dispatch("export", {}, {"id": [job["id"]], "format": ["csv"]})
            self.assertIn("checkpoint_sha256", csv)
            self.assertIn("'=unit-test", csv)
            with self.assertRaises(PermissionError):
                service.dispatch("sample", {}, {"id": [job["id"]], "index": ["0"]})


if __name__ == "__main__":
    unittest.main()
