"""Device selection and safe, portable checkpoint primitives."""

import importlib.metadata
import os
import random
import subprocess
from pathlib import Path

import numpy as np
import torch

from .config import digest
from .model import ARCHITECTURE, SkinAnalysisModel
from .transforms import PREPROCESSING


def select_cuda(uuid: str) -> torch.device:
    if torch.cuda.is_initialized():
        raise RuntimeError("Select the GPU UUID before initializing CUDA")
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=uuid,name,memory.total", "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
        check=True,
    )
    found = [
        line.split(",") for line in result.stdout.splitlines() if line.split(",")[0].strip() == uuid
    ]
    if len(found) != 1 or "4070 Ti SUPER" not in found[0][1] or float(found[0][2]) < 15000:
        raise RuntimeError("Configured UUID must identify the RTX 4070 Ti SUPER 16GB")
    os.environ["CUDA_VISIBLE_DEVICES"] = uuid
    if not torch.cuda.is_available() or "4070 Ti SUPER" not in torch.cuda.get_device_name(0):
        raise RuntimeError("The selected RTX 4070 Ti SUPER is unavailable to this PyTorch build")
    return torch.device("cuda:0")


def seed_all(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True


def capture_rng(generator: torch.Generator) -> dict:
    numpy_state = np.random.get_state()
    return {
        "python": random.getstate(),
        "numpy": [numpy_state[0], numpy_state[1].tolist(), *numpy_state[2:]],
        "torch": torch.get_rng_state(),
        "cuda": torch.cuda.get_rng_state_all() if torch.cuda.is_available() else [],
        "loader": generator.get_state(),
    }


def restore_rng(state: dict, generator: torch.Generator) -> None:
    random.setstate(state["python"])
    name, values, pos, gaussian, cached = state["numpy"]
    np.random.set_state((name, np.array(values, dtype=np.uint32), pos, gaussian, cached))
    torch.set_rng_state(state["torch"])
    if state["cuda"]:
        torch.cuda.set_rng_state_all(state["cuda"])
    generator.set_state(state["loader"])


def cpu_tree(value):
    if isinstance(value, torch.Tensor):
        return value.detach().cpu().clone()
    if isinstance(value, dict):
        return {key: cpu_tree(item) for key, item in value.items()}
    if isinstance(value, list):
        return [cpu_tree(item) for item in value]
    if isinstance(value, tuple):
        return tuple(cpu_tree(item) for item in value)
    return value


def save_checkpoint(path: Path, checkpoint: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    torch.save(checkpoint, temporary)
    temporary.replace(path)


def load_checkpoint(path: str | Path) -> dict:
    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    if checkpoint.get("schema_version") != 1 or checkpoint.get("architecture") != ARCHITECTURE:
        raise ValueError("Unsupported checkpoint schema/architecture")
    classes = checkpoint.get("classes")
    if not classes or not all(isinstance(name, str) and name for name in classes):
        raise ValueError("Checkpoint classes are missing")
    if len(set(classes)) != len(classes) or checkpoint.get("preprocessing") != PREPROCESSING:
        raise ValueError("Invalid class order or incompatible preprocessing")
    if checkpoint.get("score_type") != "sigmoid_uncalibrated":
        raise ValueError("Unsupported score semantics")
    return checkpoint


def model_from_checkpoint(checkpoint: dict, device: torch.device) -> SkinAnalysisModel:
    model = SkinAnalysisModel(len(checkpoint["classes"]), pretrained=False)
    model.load_state_dict(checkpoint["model_state"], strict=True)
    return model.to(device).eval()


def environment_metadata() -> dict:
    packages = {
        name: importlib.metadata.version(name)
        for name in (
            "torch",
            "torchvision",
            "numpy",
            "pillow",
            "scikit-learn",
            "scipy",
            "ImageHash",
        )
    }
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[3],
        check=False,
    )
    source_root = Path(__file__).parent
    source_hash = digest(
        {path.name: path.read_text(encoding="utf-8") for path in sorted(source_root.glob("*.py"))}
    )
    dirty = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        cwd=source_root.parents[2],
        check=False,
    )
    return {
        "packages": packages,
        "code_commit": result.stdout.strip() or "unknown",
        "source_hash": source_hash,
        "working_tree_dirty": bool(dirty.stdout.strip()),
        "cuda_runtime": torch.version.cuda,
        "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu",
    }
