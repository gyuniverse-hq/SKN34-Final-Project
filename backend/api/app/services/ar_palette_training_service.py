import hashlib
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from itertools import groupby
from pathlib import Path

import numpy as np

from app.core.ar_palette import CATEGORICAL, FEATURE_VERSION, FEATURES
from app.core.ar_palette_artifacts import (
    load_palette_model,
    read_json,
    score_model,
    write_json,
)
from app.core.config import get_settings
from app.core.db import dispose_engine, session_scope
from app.repositories.ar_palette_repository import ArPaletteDatasetRepository
from app.services.ar_palette_search import (
    FIXED_PARAMETERS,
    SEARCH_METHODS,
    compare_searches,
    fit_candidate,
    training_pool,
)
from app.services.member_service import TERMS_VERSION

MIN_COLLECTION_DAYS = 30


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
    comparisons = []
    for _, entries in groupby(ordered, key=lambda x: x[0]["request_id"]):
        group = list(entries)
        positive_ranks = {r["rank"] for r, _, _ in group if r["added_to_cart"]}
        if positive_ranks:

            def first(ranking, i):
                return min(ranking, key=lambda x: (-x[i], x[0]["rank"], x[0]["impression_id"]))[0]

            comparisons.append(
                (
                    group[0][0],
                    len({r["rank"] for r, _, _ in group}),
                    int(first(group, 2)["rank"] in positive_ranks),
                    int(first(group, 1)["rank"] in positive_ranks),
                )
            )

    def report(entries):
        count = len(entries)
        return {
            "positive_requests": count,
            "baseline_hit_at_1": sum(x[2] for x in entries) / count if count else None,
            "candidate_hit_at_1": sum(x[3] for x in entries) / count if count else None,
        }

    clustered = defaultdict(list)
    for row, _, old, new in comparisons:
        clustered[row["member"]].append(new - old)
    samples = np.array([(len(v), sum(v)) for v in clustered.values()])
    ci = None
    if confidence_interval and len(samples) >= 2:
        rng = np.random.default_rng(42)
        differences = []
        for _ in range(1000):
            count, net = samples[rng.integers(len(samples), size=len(samples))].sum(axis=0)
            differences.append(net / count)
        ci = np.percentile(differences, [2.5, 97.5]).tolist()
    return {
        **report(comparisons),
        "delta_ci95": ci,
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
    min_lift=None,
    code_revision=None,
    search_method=None,
):
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
    if search_method is None and baseline:
        previous_search = read_json(baseline / "manifest.json").get("search", {})
        if previous_search.get("method") in SEARCH_METHODS:
            search_method = previous_search["method"]
    method = search_method or "compare"
    if method not in ("compare", *SEARCH_METHODS):
        raise ValueError("Unknown AR search method")
    pool = training_pool(development)
    validation_rows = [r for r in validation if r["request_id"] in validation_requests]

    def evaluate(parameters):
        model = fit_candidate(pool, parameters)
        return ranked_comparison(validation_rows, model, confidence_interval=False)[
            "candidate_hit_at_1"
        ]

    search = compare_searches(evaluate, method)
    candidate = fit_candidate(training_pool(development + validation), search["parameters"])
    params = {**FIXED_PARAMETERS, **search["parameters"]}
    metrics = ranked_comparison(evaluation, candidate, champion)
    passes = None
    if min_hit is not None and min_lift is not None:
        passes = (
            metrics["candidate_hit_at_1"] >= min_hit
            and metrics["candidate_hit_at_1"] - metrics["baseline_hit_at_1"] >= min_lift
            and metrics["delta_ci95"] is not None
            and metrics["delta_ci95"][0] > 0
        )
    report = {
        "status": "candidate_created",
        "baseline": champion_id,
        "offline_pass": passes,
        "thresholds": {"hit_at_1": min_hit, "lift": min_lift},
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
            "features": FEATURES,
            "categorical": CATEGORICAL,
            "source": data["source"],
            "code_revision": code_revision,
            "parameters": params,
            "search": {
                key: search[key]
                for key in ("method", "trials_per_method", "objective", "best_validation_hit_at_1")
            },
            "data_as_of": data.get("as_of"),
            "catalog_versions": data.get("catalog_versions", []),
            "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
            "model_sha256": hashlib.sha256(model_file.read_bytes()).hexdigest(),
            "offline_pass": passes,
        },
    )
    return report


def summarize_experiment(rows, *, min_sessions=None, min_lift=None, finished=False):
    clusters = {"A": defaultdict(list), "B": defaultdict(list)}
    counts = {arm: Counter() for arm in clusters}
    versions = {arm: set() for arm in clusters}
    for row in rows:
        arm = row["arm"]
        versions[arm].update(row.get("model_versions") or ())
        clusters[arm][row["member_id"]].append(int(row["added_to_cart"]))
        counts[arm].update(
            {
                "sessions": 1,
                "cart_sessions": int(row["added_to_cart"]),
                "fallback_sessions": int(row["fallback"]),
                "empty_sessions": int(row["empty"]),
            }
        )
    if clusters["A"].keys() & clusters["B"].keys():
        raise ValueError("Member appears in both AR experiment arms")
    arms = {}
    rates = {}
    for arm, counter in counts.items():
        rate = counter["cart_sessions"] / counter["sessions"] if counter["sessions"] else None
        rates[arm] = rate
        arms[arm] = {
            **{
                key: counter[key]
                for key in ("sessions", "cart_sessions", "fallback_sessions", "empty_sessions")
            },
            "members": len(clusters[arm]),
            "cart_rate": rate,
            "model_versions": sorted(versions[arm]),
        }
    ci = delta = None
    if all(rate is not None for rate in rates.values()):
        delta = rates["B"] - rates["A"]
    if all(len(groups) >= 2 for groups in clusters.values()):
        rng = np.random.default_rng(42)

        def bootstrap(groups):
            data = np.array([(len(v), sum(v)) for v in groups.values()])
            sampled_rates = []
            for _ in range(1000):
                total, carts = data[rng.integers(len(data), size=len(data))].sum(axis=0)
                sampled_rates.append(carts / total)
            return np.array(sampled_rates)

        ci = np.percentile(bootstrap(clusters["B"]) - bootstrap(clusters["A"]), [2.5, 97.5])
        ci = ci.tolist()
    ready = (
        finished
        and not versions["A"]
        and len(versions["B"]) == 1
        and min_sessions is not None
        and min_lift is not None
        and all(counter["sessions"] >= min_sessions for counter in counts.values())
    )
    return {
        "arms": arms,
        "lift": delta,
        "lift_ci95": ci,
        "result": "pending"
        if not ready
        else "passed"
        if ci and ci[0] > 0 and delta >= min_lift
        else "retain_baseline",
        "purchase_metrics": "unmeasured",
    }


async def experiment_report(
    output, *, experiment, start, end, as_of, window, grace, min_sessions=None, min_lift=None
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
                members=settings.ar_activity_consented_members,
                terms=TERMS_VERSION,
            )
    finally:
        await dispose_engine()
    report = {
        "experiment": experiment,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "as_of": as_of.isoformat(),
        "min_sessions_per_arm": min_sessions,
        "min_lift": min_lift,
        **summarize_experiment(
            rows,
            min_sessions=min_sessions,
            min_lift=min_lift,
            finished=as_of >= end + window + grace,
        ),
    }
    write_json(output, report)
    return report
