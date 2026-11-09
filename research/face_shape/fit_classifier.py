"""Fit the small face-shape classifier (standardise + multinomial logistic regression) on features.csv.

    python research/face_shape/fit_classifier.py [dataset_dir]

C is chosen on the valid split; the test split is touched once for the reported numbers. Writes model.json
(means, stds, weights, biases: numbers only) and RESULTS.md next to this file.
"""
import json
import sys
from pathlib import Path

import csv

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import confusion_matrix
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).parent))
from features import FEATURES  # noqa: E402

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
DEFAULT = ROOT / "research/data/reference/face_shape/ashish-workspace__face-shape-classification-yoqx4-lfvhe__v1"
CLASSES = ["Round", "Square", "Oblong", "Heart", "Oval"]  # app keys: round, square, oblong, heart, oval


def main() -> None:
    data = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    with (data / "features.csv").open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    split = np.array([r["split"] for r in rows])
    Xall = np.array([[float(r[k]) for k in FEATURES] for r in rows])
    yall = np.array([CLASSES.index(r["cls"]) for r in rows])
    sel = lambda *names: np.isin(split, names)
    Xtr, ytr, Xva, yva, Xte, yte = Xall[sel("train")], yall[sel("train")], Xall[sel("valid")], yall[sel("valid")], Xall[sel("test")], yall[sel("test")]
    Xtv, ytv = Xall[sel("train", "valid")], yall[sel("train", "valid")]
    n_total = len(rows)

    best = None
    for C in (0.01, 0.03, 0.1, 0.3, 1, 3, 10):
        m = make_pipeline(StandardScaler(), LogisticRegression(C=C, max_iter=2000)).fit(Xtr, ytr)
        acc = m.score(Xva, yva)
        print(f"C={C:<5} valid acc {acc:.3f}")
        if best is None or acc > best[0]:
            best = (acc, C)
    C = best[1]
    m = make_pipeline(StandardScaler(), LogisticRegression(C=C, max_iter=2000)).fit(Xtv, ytv)
    pred = m.predict(Xte)
    test_acc = float((pred == yte).mean())
    cm = confusion_matrix(yte, pred, labels=range(5))
    cv = cross_val_score(make_pipeline(StandardScaler(), LogisticRegression(C=C, max_iter=2000)), Xtv, ytv,
                         cv=StratifiedKFold(5, shuffle=True, random_state=0))
    proba = m.predict_proba(Xte)
    conf = proba.max(1)
    top2 = float(np.mean([yte[i] in np.argsort(-proba[i])[:2] for i in range(len(yte))]))
    chance = float(np.bincount(yte).max() / len(yte))
    print(f"C={C} test acc {test_acc:.3f} (chance {chance:.3f}) top2 {top2:.3f} cv {cv.mean():.3f}+-{cv.std():.3f}")

    sc, lr = m.named_steps["standardscaler"], m.named_steps["logisticregression"]
    model = {
        "classes": [c.lower() for c in CLASSES],
        "features": FEATURES,
        "mean": [round(float(v), 5) for v in sc.mean_],
        "std": [round(float(v), 5) for v in sc.scale_],
        "W": [[round(float(v), 4) for v in row] for row in lr.coef_],
        "b": [round(float(v), 4) for v in lr.intercept_],
    }
    (HERE / "model.json").write_text(json.dumps(model, indent=1), encoding="utf-8")

    lines = [
        "# Face-shape classifier (offline calibration)", "",
        "Data: Roboflow Universe `ashish-workspace/face-shape-classification-yoqx4-lfvhe` v1, CC BY 4.0 (page lists no image "
        "provenance or consent; images stay in git-ignored `research/data/`, only the fitted numbers are committed).",
        f"Frontal photos kept (yaw 0.85-1.18, roll <= 10 deg): {n_total} of 4002. Labels are the uploader's, not a clinical standard.", "",
        f"Model: standardise + multinomial logistic regression, C={C} (chosen on valid), refit on train+valid.", "",
        f"- test accuracy **{test_acc:.3f}** (n={len(yte)}; chance by majority class {chance:.3f}), top-2 {top2:.3f}",
        f"- 5-fold CV on train+valid {cv.mean():.3f} +- {cv.std():.3f}",
        f"- mean max probability on test {conf.mean():.3f}", "",
        "Confusion matrix (rows = label, columns = prediction):", "",
        "| | " + " | ".join(CLASSES) + " |", "|---|" + "---|" * 5,
    ]
    for i, row in enumerate(cm):
        lines.append(f"| {CLASSES[i]} | " + " | ".join(str(v) for v in row) + " |")
    lines += ["", "Standardised weights per class (rows) and feature (columns):", "",
              "| | " + " | ".join(FEATURES) + " |", "|---|" + "---|" * len(FEATURES)]
    for i, row in enumerate(lr.coef_):
        lines.append(f"| {CLASSES[i]} | " + " | ".join(f"{v:+.2f}" for v in row) + " |")
    lines += ["", "Read as: a measured estimate with a probability, not a diagnosis. The app shows the top class with its "
              "probability and blends the shading rules by probability."]
    (HERE / "RESULTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
