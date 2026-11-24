"""Shared scoring, identity, provenance and statistical helpers."""
import csv
import hashlib
import json
import math
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = ROOT / "research/data/lip_rubric"


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf8"))


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fields=None):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fields = fields or list(rows[0])
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)


def checks(rubric):
    return [item for question in rubric["questions"] for item in question["checks"]]


def allows_na(check, finish):
    cond = check.get("na_allowed", False)
    return cond is True or (isinstance(cond, dict) and finish in cond.get("finish", []))


def score(rubric, answers, finish):
    values = []
    normalized = {}
    for question in rubric["questions"]:
        bits = []
        for check in question["checks"]:
            raw = answers.get(check["id"])
            value = str(raw).strip().lower()
            if value == "na":
                if not allows_na(check, finish):
                    raise ValueError(f"{check['id']}: na not allowed for {finish}")
                normalized[check["id"]] = "na"
            elif value in ("0", "1"):
                normalized[check["id"]] = int(value); bits.append(int(value))
            else:
                raise ValueError(f"{check['id']}: expected 0, 1 or allowed na")
        values.append(sum(bits) / len(bits) if bits else None)
    valid = [x for x in values if x is not None]
    return {"questions": values, "total": 5 * sum(valid) / len(valid) if valid else None, "checks": normalized}


def ranks(values):
    a = np.asarray(values, dtype=float)
    order = np.argsort(a, kind="stable"); out = np.empty(len(a), dtype=float)
    start = 0
    while start < len(a):
        end = start + 1
        while end < len(a) and a[order[end]] == a[order[start]]:
            end += 1
        out[order[start:end]] = (start + 1 + end) / 2
        start = end
    return out


def spearman(a, b):
    pairs = [(float(x), float(y)) for x, y in zip(a, b) if x is not None and y is not None and np.isfinite(float(x)) and np.isfinite(float(y))]
    if len(pairs) < 3:
        return None
    x, y = map(np.asarray, zip(*pairs)); x, y = ranks(x), ranks(y)
    if np.std(x) == 0 or np.std(y) == 0:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def cluster_bootstrap(items, func, seed=42, n=2000):
    groups = sorted({x["face_id"] for x in items})
    observed = func(items)
    if len(groups) < 2 or observed is None:
        return {"estimate": observed, "ci95": None, "clusters": len(groups), "valid_replicates": 0}
    by_group = {g: [x for x in items if x["face_id"] == g] for g in groups}
    rng = np.random.default_rng(seed); samples = []
    for _ in range(n):
        pick = rng.choice(groups, len(groups), replace=True)
        value = func([r for group in pick for r in by_group[group]])
        if value is not None and math.isfinite(value):
            samples.append(value)
    interval = np.percentile(samples, [2.5, 97.5]).tolist() if len(samples) >= 2 else None
    return {"estimate": observed, "ci95": interval, "clusters": len(groups), "valid_replicates": len(samples)}


def icc2(matrix):
    """ICC(2,1), ICC(2,k): two-way random absolute agreement, balanced data."""
    a = np.asarray(matrix, dtype=float)
    if a.ndim != 2 or min(a.shape) < 2 or not np.isfinite(a).all():
        return {"icc_2_1": None, "icc_2_k": None, "n": int(a.shape[0]) if a.ndim else 0}
    n, k = a.shape; grand = a.mean(); row = a.mean(axis=1); col = a.mean(axis=0)
    msr = k * np.sum((row-grand)**2) / (n-1)
    msc = n * np.sum((col-grand)**2) / (k-1)
    mse = np.sum((a-row[:, None]-col[None, :]+grand)**2) / ((n-1)*(k-1))
    numerator = msr-mse
    d1 = msr+(k-1)*mse+k*(msc-mse)/n; dk = msr+(msc-mse)/n
    return {"icc_2_1": float(numerator/d1) if d1 else None, "icc_2_k": float(numerator/dk) if dk else None, "n": n, "raters": k}


def krippendorff_alpha(units, ordinal=False):
    """Coincidence-weighted Krippendorff alpha, supports missing observations."""
    data = [[v for v in unit if v is not None] for unit in units]
    data = [row for row in data if len(row) >= 2]
    categories = sorted({x for row in data for x in row})
    if not data or len(categories) < 2:
        return None
    idx = {c:i for i,c in enumerate(categories)}; observed = np.zeros((len(categories),len(categories)))
    for row in data:
        counts = np.zeros(len(categories))
        for value in row: counts[idx[value]] += 1
        observed += (np.outer(counts, counts)-np.diag(counts))/(len(row)-1)
    marg = observed.sum(axis=0); total = marg.sum()
    if total <= 1:
        return None
    expected = (np.outer(marg,marg)-np.diag(marg))/(total-1)
    distance = np.zeros_like(observed)
    for i in range(len(categories)):
        for j in range(len(categories)):
            if i != j:
                lo, hi = sorted((i,j))
                distance[i,j] = (sum(marg[lo:hi+1])-(marg[lo]+marg[hi])/2)**2 if ordinal else 1
    do = float((observed*distance).sum()); de = float((expected*distance).sum())
    return 1-do/de if de else None
