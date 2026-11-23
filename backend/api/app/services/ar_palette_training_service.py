import hashlib
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from itertools import groupby
from math import log2
from pathlib import Path

import numpy as np

from app.core.ar_palette import CATEGORICAL, FEATURE_VERSION, FEATURES
from app.core.ar_palette_artifacts import (
    CLASSIFIER,
    RANKER,
    load_palette_model,
    read_json,
    score_model,
    write_json,
)
from app.core.config import get_settings
from app.core.db import dispose_engine, session_scope
from app.repositories.ar_palette_repository import ArPaletteDatasetRepository
from app.services.ar_palette_search import (
    MODEL_PARAMETERS,
    SEARCH_METHODS,
    compare_searches,
    fit_candidate,
    training_pool,
)
from app.services.member_service import TERMS_VERSION

MIN_COLLECTION_DAYS = 30
NDCG_DISCOUNTS = tuple(1 / log2(rank + 1) for rank in range(1, 4))
RANKING_METRICS = ("hit_at_1", "ndcg_at_3")


def member_key(member_id):
    return hashlib.sha256(f"ar-palette-group:{member_id}".encode()).hexdigest()


async def export_dataset(output, *, as_of, window, grace):
    settings = get_settings()
    rows = []
    exclusions = Counter()
    previous = snapshot = None
    try:
        async with session_scope() as session:
            repo = ArPaletteDatasetRepository(session)
            async for row in repo.exposures(
                as_of=as_of,
                window=window,
                grace=grace,
                members=settings.ar_activity_consented_members,
                terms=TERMS_VERSION,
            ):
                request_id = str(row["request_id"])
                if request_id != previous:
                    previous = request_id
                    snapshot = None
                    path = settings.ar_palette_data_dir / "snapshots" / f"{request_id}.json"
                    try:
                        snapshot = read_json(path)
                    except FileNotFoundError:
                        pass
                    except (OSError, ValueError):
                        snapshot = {}
                    if snapshot is not None and not isinstance(snapshot, dict):
                        snapshot = {}
                saved_features = (snapshot or {}).get("features")
                features = (
                    saved_features.get(str(row["candidate_id"]))
                    if isinstance(saved_features, dict)
                    else None
                )
                if snapshot is None:
                    exclusions["missing_snapshot"] += 1
                elif (
                    snapshot.get("feature_version") != FEATURE_VERSION
                    or snapshot.get("policy_version") != row["policy_version"]
                    or snapshot.get("requested_at") != row["created_at"].astimezone(UTC).isoformat()
                    or not isinstance(features, dict)
                    or set(features) != set(FEATURES)
                    or features["makeup_zone"] != row["makeup_zone"]
                ):
                    exclusions["invalid_snapshot"] += 1
                else:
                    rows.append(
                        {
                            "impression_id": str(row["impression_id"]),
                            "request_id": request_id,
                            "session_id": str(row["session_id"]),
                            "member": member_key(row["member_id"]),
                            "requested_at": row["created_at"].astimezone(UTC).isoformat(),
                            "rank": row["rank"],
                            "policy_version": row["policy_version"],
                            "catalog_digest": snapshot.get("catalog_digest"),
                            "features": features,
                            "added_to_cart": int(row["added_to_cart"]),
                        }
                    )
    finally:
        await dispose_engine()
    metadata = {
        "feature_version": FEATURE_VERSION,
        "source": "db",
        "as_of": as_of.isoformat(),
        "label_window_seconds": window.total_seconds(),
        "receipt_grace_seconds": grace.total_seconds(),
        "exclusions": dict(exclusions),
        "catalog_versions": sorted({r["catalog_digest"] for r in rows if r["catalog_digest"]}),
    }
    write_json(output, {**metadata, "rows": rows})
    return {**metadata, **summarize(rows)}


def summarize(rows):
    positives = sum(row["added_to_cart"] for row in rows)
    return {
        "rows": len(rows),
        "positive_impressions": positives,
        "negative_impressions": len(rows) - positives,
        "mixed_label_requests": len(mixed_label_requests(rows)),
        "impression_cart_rate": positives / len(rows) if rows else None,
        "members": len({r["member"] for r in rows}),
        "positive_requests": len({r["request_id"] for r in rows if r["added_to_cart"]}),
        "positive_requests_by_zone": {
            zone: len(
                {
                    r["request_id"]
                    for r in rows
                    if r["added_to_cart"] and r["features"]["makeup_zone"] == zone
                }
            )
            for zone in ("lip", "blush")
        },
    }


def synthetic_dataset(output):
    rows = []
    for request in range(36):
        for rank in range(1, 4):
            features = dict(
                zip(
                    FEATURES,
                    (
                        "lip" if request % 2 else "blush",
                        ("red", "pink", "coral")[rank - 1],
                        45 + rank * 8,
                        18 + rank * 9,
                        "matte" if rank == 1 else "glossy",
                        4.7 - rank * 0.1,
                        25 + rank * 25,
                        request % 5,
                        None if request % 5 == 0 else rank / 3,
                        None if request % 5 == 0 else 0.5,
                    ),
                    strict=True,
                )
            )
            rows.append(
                {
                    "request_id": f"demo-{request}",
                    "session_id": f"demo-{request}",
                    "impression_id": f"demo-{request}-{rank}",
                    "member": f"demo-{request % 12}",
                    "requested_at": (
                        datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=request)
                    ).isoformat(),
                    "rank": rank,
                    "features": features,
                    "added_to_cart": int(rank == 2),
                }
            )
    write_json(output, {"feature_version": FEATURE_VERSION, "source": "synthetic", "rows": rows})
    return summarize(rows)


def mixed_label_requests(rows):
    labels = defaultdict(dict)
    for row in rows:
        candidates = labels[row["request_id"]]
        rank = row["rank"]
        candidates[rank] = max(candidates.get(rank, 0), row["added_to_cart"])
    return {request for request, candidates in labels.items() if set(candidates.values()) == {0, 1}}


def temporal_split(rows):
    ordered = sorted(rows, key=lambda row: (row["requested_at"], row["request_id"]))
    request_times = list({row["request_id"]: row["requested_at"] for row in ordered}.values())
    if len(request_times) < 3:
        return [], [], [], {}
    validation_cutoff = request_times[len(request_times) * 70 // 100]
    test_cutoff = request_times[len(request_times) * 85 // 100]
    partitions = ([], [], [])
    session_folds = {}
    for row in reversed(ordered):
        at = row["requested_at"]
        fold = 2 if at >= test_cutoff else 1 if at >= validation_cutoff else 0
        session = (row["member"], row["session_id"])
        # Keep the later interval for sessions that span a boundary.
        if session_folds.setdefault(session, fold) == fold:
            partitions[fold].append(row)
    for part in partitions:
        part.reverse()
    return (*partitions, {"validation": validation_cutoff, "test": test_cutoff})


def ranked_comparison(rows, candidate, baseline_bundle=None, *, confidence_interval=True):
    proposed = score_model(candidate, [r["features"] for r in rows])
    baseline = (
        score_model(baseline_bundle, [r["features"] for r in rows])
        if baseline_bundle is not None
        else [-r["rank"] for r in rows]
    )
    ordered = sorted(zip(rows, proposed, baseline, strict=True), key=lambda x: x[0]["request_id"])

    def metrics_at(group, score_index, positive_ranks):
        ranking = sorted(
            group, key=lambda x: (-x[score_index], x[0]["rank"], x[0]["impression_id"])
        )
        # A candidate can have multiple impressions of the same recorded slot.
        positions = list(dict.fromkeys(row["rank"] for row, _, _ in ranking))
        dcg = sum(
            discount
            for rank, discount in zip(positions, NDCG_DISCOUNTS, strict=False)
            if rank in positive_ranks
        )
        return int(positions[0] in positive_ranks), dcg / sum(NDCG_DISCOUNTS[: len(positive_ranks)])

    comparisons = []
    for _, entries in groupby(ordered, key=lambda x: x[0]["request_id"]):
        group = list(entries)
        positive_ranks = {r["rank"] for r, _, _ in group if r["added_to_cart"]}
        if not positive_ranks:
            continue

        comparisons.append(
            (
                group[0][0],
                len({r["rank"] for r, _, _ in group}),
                metrics_at(group, 2, positive_ranks),
                metrics_at(group, 1, positive_ranks),
            )
        )

    def report(entries):
        count = len(entries)
        return {
            "positive_requests": count,
            **{
                f"{side}_{metric}": sum(entry[index][i] for entry in entries) / count
                if count
                else None
                for i, metric in enumerate(RANKING_METRICS)
                for side, index in (("baseline", 2), ("candidate", 3))
            },
        }

    clustered = defaultdict(list)
    if confidence_interval:
        for row, _, old, new in comparisons:
            clustered[row["member"]].append([b - a for a, b in zip(old, new, strict=True)])
    hit_ci = ndcg_ci = None
    if len(clustered) >= 2:
        samples = np.array([(len(v), *np.sum(v, axis=0)) for v in clustered.values()])
        rng = np.random.default_rng(42)
        differences = []
        for _ in range(1000):
            sampled = samples[rng.integers(len(samples), size=len(samples))].sum(axis=0)
            differences.append(sampled[1:] / sampled[0])
        hit_ci, ndcg_ci = np.percentile(differences, [2.5, 97.5], axis=0).T.tolist()
    return {
        **report(comparisons),
        "delta_ci95": hit_ci,
        "ndcg_at_3_delta_ci95": ndcg_ci,
        "multi_candidate": report([x for x in comparisons if x[1] >= 2]),
        "by_zone": {
            zone: report([x for x in comparisons if x[0]["features"]["makeup_zone"] == zone])
            for zone in ("lip", "blush")
        },
    }


def collection_days(data, rows):
    if not rows or not data.get("as_of"):
        return 0.0
    first = datetime.fromisoformat(min(row["requested_at"] for row in rows))
    closed_through = datetime.fromisoformat(data["as_of"]) - timedelta(
        seconds=data["label_window_seconds"] + data["receipt_grace_seconds"]
    )
    return max(0.0, (closed_through - first).total_seconds() / 86_400)


def train_dataset(
    dataset: Path,
    output: Path,
    *,
    baseline=None,
    min_hit=None,
    min_ndcg=None,
    min_lift=None,
    code_revision=None,
    search_method=None,
    model_type=RANKER,
):
    if model_type not in MODEL_PARAMETERS:
        raise ValueError("Unknown AR model type")
    if min_hit is not None and min_ndcg is not None:
        raise ValueError("Choose one AR offline threshold metric")
    data = read_json(dataset)
    if data["feature_version"] != FEATURE_VERSION or data["source"] not in ("db", "synthetic"):
        raise ValueError("Invalid AR dataset contract")
    rows = data["rows"]
    if baseline is None and data["source"] == "db":
        rows = [row for row in rows if row["policy_version"].split(":")[-1] in ("rule", "fallback")]
    summary = summarize(rows)
    days = collection_days(data, rows) if data["source"] == "db" else None
    if days is not None and days < MIN_COLLECTION_DAYS:
        return {
            "status": "skipped",
            "reason": "insufficient_collection_days",
            "required_collection_days": MIN_COLLECTION_DAYS,
            "collection_days": days,
            **summary,
        }
    development, validation, evaluation, cutoffs = temporal_split(rows)
    split = {
        "development": summarize(development),
        "validation": summarize(validation),
        "evaluation": summarize(evaluation),
        "cutoffs": cutoffs,
    }
    validation_requests = mixed_label_requests(validation)
    if (
        {r["added_to_cart"] for r in development} != {0, 1}
        or (model_type == RANKER and not mixed_label_requests(development))
        or not validation_requests
        or not mixed_label_requests(evaluation)
    ):
        return {
            "status": "skipped",
            "reason": "insufficient_split_classes_or_comparable_requests",
            "collection_days": days,
            **summary,
            **split,
        }
    champion, champion_id, _ = (
        load_palette_model(baseline.resolve(), allow_synthetic=data["source"] == "synthetic")
        if baseline
        else (None, "recorded-rule-rank", None)
    )
    if search_method is None and model_type == CLASSIFIER and baseline:
        previous_manifest = read_json(baseline / "manifest.json")
        previous_search = previous_manifest.get("search", {})
        if (
            previous_manifest.get("model_type", CLASSIFIER) == CLASSIFIER
            and previous_search.get("method") in SEARCH_METHODS
        ):
            search_method = previous_search["method"]
    method = search_method or ("random" if model_type == RANKER else "compare")
    if method not in ("compare", *SEARCH_METHODS):
        raise ValueError("Unknown AR search method")
    search_metric = "ndcg_at_3" if model_type == RANKER else "hit_at_1"
    pool = training_pool(development, model_type=model_type)
    validation_rows = [r for r in validation if r["request_id"] in validation_requests]

    def evaluate(parameters):
        model = fit_candidate(pool, parameters, model_type=model_type)
        return ranked_comparison(validation_rows, model, confidence_interval=False)[
            f"candidate_{search_metric}"
        ]

    search = compare_searches(evaluate, method, metric=search_metric)
    refit_pool = training_pool(development + validation, model_type=model_type)
    candidate = fit_candidate(refit_pool, search["parameters"], model_type=model_type)
    params = {**MODEL_PARAMETERS[model_type], **search["parameters"]}
    metrics = ranked_comparison(evaluation, candidate, champion)
    decision_metric = search_metric
    if min_hit is not None:
        decision_metric = "hit_at_1"
    elif min_ndcg is not None:
        decision_metric = "ndcg_at_3"
    threshold = min_ndcg if decision_metric == "ndcg_at_3" else min_hit
    ci = metrics["ndcg_at_3_delta_ci95" if decision_metric == "ndcg_at_3" else "delta_ci95"]
    passes = None
    if threshold is not None and min_lift is not None:
        score = metrics[f"candidate_{decision_metric}"]
        passes = (
            score >= threshold
            and score - metrics[f"baseline_{decision_metric}"] >= min_lift
            and ci is not None
            and ci[0] > 0
        )
    report = {
        "status": "candidate_created",
        "model_type": model_type,
        "baseline": champion_id,
        "offline_pass": passes,
        "decision_metric": decision_metric,
        "thresholds": {decision_metric: threshold, "lift": min_lift},
        "collection_days": days,
        **split,
        "search": search,
        "metrics": metrics,
    }
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("AR model output directory must be empty")
    model_file = output / "model.cbm"
    candidate.save_model(str(model_file))
    write_json(output / "metrics.json", report)
    write_json(
        output / "manifest.json",
        {
            "feature_version": FEATURE_VERSION,
            "model_type": model_type,
            "features": FEATURES,
            "categorical": CATEGORICAL,
            "source": data["source"],
            "code_revision": code_revision,
            "parameters": params,
            "search": {
                key: search[key]
                for key in (
                    "method",
                    "trials_per_method",
                    "objective",
                    f"best_validation_{search_metric}",
                )
            },
            "data_as_of": data.get("as_of"),
            "catalog_versions": data.get("catalog_versions", []),
            "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
            "model_sha256": hashlib.sha256(model_file.read_bytes()).hexdigest(),
            "offline_pass": passes,
        },
    )
    return report


def experiment_lift(clusters, numerator, denominator):
    samples = {
        arm: np.array([(c[numerator], c[denominator]) for c in members.values()]).reshape(-1, 2)
        for arm, members in clusters.items()
    }
    totals = {arm: data.sum(axis=0) for arm, data in samples.items()}
    if not all(count for _, count in totals.values()):
        return None, None
    delta = float(totals["B"][0] / totals["B"][1] - totals["A"][0] / totals["A"][1])
    if not all(len(data) >= 2 for data in samples.values()):
        return delta, None
    rng = np.random.default_rng(42)

    def bootstrap(data):
        sums = np.array(
            [data[rng.integers(len(data), size=len(data))].sum(axis=0) for _ in range(1000)]
        )
        return np.divide(
            sums[:, 0], sums[:, 1], out=np.full(len(sums), np.nan), where=sums[:, 1] != 0
        )

    differences = bootstrap(samples["B"]) - bootstrap(samples["A"])
    finite = differences[np.isfinite(differences)]
    return delta, np.percentile(finite, [2.5, 97.5]).tolist() if len(finite) else None


def summarize_experiment(
    rows, *, min_sessions=None, min_lift=None, finished=False, measure_purchase=False
):
    clusters = {"A": defaultdict(Counter), "B": defaultdict(Counter)}
    counts = {arm: Counter() for arm in clusters}
    versions = {arm: set() for arm in clusters}
    for row in rows:
        arm = row["arm"]
        versions[arm].update(row.get("model_versions") or ())
        session = {
            "sessions": 1,
            "cart_sessions": int(row["added_to_cart"]),
            "purchase_sessions": int(row["added_to_cart"] and row.get("purchased", False)),
            "rule_sessions": int(row.get("served_rule", False)),
            "fallback_sessions": int(row["fallback"]),
            "empty_sessions": int(row["empty"]),
        }
        clusters[arm][row["member_id"]].update(session)
        counts[arm].update(session)
    if clusters["A"].keys() & clusters["B"].keys():
        raise ValueError("Member appears in both AR experiment arms")
    arms = {}
    for arm, counter in counts.items():
        sessions, carts, purchases = (
            counter[k] for k in ("sessions", "cart_sessions", "purchase_sessions")
        )
        arms[arm] = {
            **{
                key: counter[key]
                for key in (
                    "sessions",
                    "cart_sessions",
                    "rule_sessions",
                    "fallback_sessions",
                    "empty_sessions",
                )
            },
            "members": len(clusters[arm]),
            "cart_rate": carts / sessions if sessions else None,
            "model_versions": sorted(versions[arm]),
        }
        if measure_purchase:
            arms[arm].update(
                purchase_sessions=purchases,
                cart_to_purchase_rate=purchases / carts if carts else None,
                session_to_purchase_rate=purchases / sessions if sessions else None,
            )
    delta, ci = experiment_lift(clusters, "cart_sessions", "sessions")
    decision_lift, decision_ci = None, None
    purchase_metrics = "unmeasured"
    if measure_purchase:
        cart_lift, cart_ci = experiment_lift(clusters, "purchase_sessions", "cart_sessions")
        decision_lift, decision_ci = experiment_lift(clusters, "purchase_sessions", "sessions")
        purchase_metrics = {
            "cart_to_purchase_lift": cart_lift,
            "cart_to_purchase_lift_ci95": cart_ci,
            "session_to_purchase_lift": decision_lift,
            "session_to_purchase_lift_ci95": decision_ci,
        }
    rule_baseline = counts["A"]["rule_sessions"] > 0 and not versions["A"]
    stable_model = {
        arm: counts[arm]["rule_sessions"] == 0
        and len(model_versions) == 1
        and all(version.startswith("m-") for version in model_versions)
        for arm, model_versions in versions.items()
    }
    ml_baseline = stable_model["A"] and versions["A"].isdisjoint(versions["B"])
    ready = (
        measure_purchase
        and finished
        and stable_model["B"]
        and (rule_baseline or ml_baseline)
        and min_sessions is not None
        and min_lift is not None
        and all(counter["sessions"] >= min_sessions for counter in counts.values())
    )
    return {
        "arms": arms,
        "lift": delta,
        "lift_ci95": ci,
        "decision_metric": "session_to_purchase_rate",
        "result": "pending"
        if not ready
        else "passed"
        if decision_ci and decision_ci[0] > 0 and decision_lift >= min_lift
        else "retain_baseline",
        "purchase_metrics": purchase_metrics,
    }


async def experiment_report(
    output,
    *,
    experiment,
    start,
    end,
    as_of,
    window,
    grace,
    min_sessions=None,
    min_lift=None,
    purchase_window=None,
):
    settings = get_settings()
    try:
        async with session_scope() as session:
            rows = await ArPaletteDatasetRepository(session).experiment_sessions(
                experiment=experiment,
                start=start,
                end=end,
                as_of=as_of,
                window=window,
                grace=grace,
                purchase_window=purchase_window,
                members=settings.ar_activity_consented_members,
                terms=TERMS_VERSION,
            )
    finally:
        await dispose_engine()
    mature = [row for row in rows if row["mature"]]
    observation = max(window + grace, purchase_window or window)
    report = {
        "experiment": experiment,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "as_of": as_of.isoformat(),
        "min_sessions_per_arm": min_sessions,
        "min_lift": min_lift,
        "purchase_window_seconds": purchase_window.total_seconds() if purchase_window else None,
        "pending_sessions": len(rows) - len(mature),
        **summarize_experiment(
            mature,
            min_sessions=min_sessions,
            min_lift=min_lift,
            finished=as_of >= end + observation and len(mature) == len(rows),
            measure_purchase=purchase_window is not None,
        ),
    }
    write_json(output, report)
    return report
