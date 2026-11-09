"""Write __tests__/fixtures/faceShapeParity.json: seeded synthetic landmarks + the Python features / probabilities.

The Jest test runs the page's faceShapeFeatures / shapeProbs on the same landmarks and must agree, so the JS in
components/ar/faceTrackerHtml.ts stays the same function the model was fitted with. Synthetic points on purpose:
no real face geometry is committed.

    python research/face_shape/make_parity_fixture.py
"""
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from features import FEATURES, features  # noqa: E402

ROOT = HERE.parents[1]
model = json.loads((HERE / "model.json").read_text(encoding="utf-8"))


def probs(f):
    z = np.array([(f[k] - model["mean"][i]) / model["std"][i] for i, k in enumerate(model["features"])])
    logit = np.array(model["W"]) @ z + np.array(model["b"])
    e = np.exp(logit - logit.max())
    return (e / e.sum()).tolist()


rng = np.random.default_rng(7)
cases = []
for w, h in [(720, 960), (1080, 1920)]:
    # an oval-ish cloud with the landmarks the features use placed deliberately, the rest random
    L = np.stack([rng.uniform(0.3, 0.7, 468), rng.uniform(0.2, 0.85, 468), rng.uniform(-0.05, 0.05, 468)], axis=1)
    L[234] = [0.28, 0.5, 0.02]; L[454] = [0.72, 0.5, -0.01]; L[10] = [0.5, 0.18, 0.0]; L[152] = [0.5, 0.88, 0.03]
    L[172] = [0.34, 0.74, 0.02]; L[397] = [0.66, 0.74, 0.0]; L[54] = [0.36, 0.2, 0.0]; L[284] = [0.64, 0.2, 0.0]
    L[132] = [0.30, 0.64, 0.02]; L[361] = [0.70, 0.64, 0.0]; L[148] = [0.45, 0.86, 0.03]; L[377] = [0.55, 0.86, 0.03]
    L[1] = [0.5, 0.5, 0.08]
    f = features([tuple(r) for r in L], w, h)
    cases.append({"w": w, "h": h, "x": L[:, 0].round(6).tolist(), "y": L[:, 1].round(6).tolist(), "z": L[:, 2].round(6).tolist(),
                  "features": {k: f[k] for k in FEATURES}, "probs": None})
    # the fixture rounds coordinates, so recompute from the rounded values
    Lr = np.stack([cases[-1]["x"], cases[-1]["y"], cases[-1]["z"]], axis=1)
    f = features([tuple(r) for r in Lr], w, h)
    cases[-1]["features"] = {k: f[k] for k in FEATURES}
    cases[-1]["probs"] = probs(f)
out = ROOT / "__tests__" / "fixtures" / "faceShapeParity.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(cases), encoding="utf-8")
print("wrote", out.relative_to(ROOT))
