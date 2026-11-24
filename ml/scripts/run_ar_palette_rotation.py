"""Compare 7-day rotation policies on the saved AR palette experiment."""

import argparse
import hashlib
import os
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.font_manager import FontProperties
from matplotlib.ticker import MaxNLocator, PercentFormatter
from ml.scripts import run_ar_palette_bpr as study
from ml.scripts.run_ar_palette_bpr_mf import item_key, load_holdout

MODEL_METHODS = {"classifier": "optuna", "pairlogit": "random"}
ROTATION_POLICIES = ("before", "after", "all")
POLICIES = (*ROTATION_POLICIES, "try_on")
WINDOW = timedelta(days=7)
TRY_ON_WINDOW = timedelta(days=90)
MIN_TRY_ONS_TO_RESHOW = 2
TRY_ON_AFFINITY_WEIGHT = 0.20
RELEVANCE_DRAWS = 128
REFERENCE_RANK = 2


@dataclass(frozen=True)
class TryOnHistory:
    counts: Counter[study.ShadeKey]
    carted: set[study.ShadeKey]
    repeat_candidates: set[study.ShadeKey]


def restore_requests(dataset, test):
    catalog_digest = hashlib.sha256(study.CATALOG.read_bytes()).hexdigest()
    if catalog_digest != dataset["catalog_sha256"]:
        raise ValueError("The seed catalog differs from the saved mock run")
    exposure_counts = Counter(row["request_id"] for row in test)
    requests = []

    def capture(request):
        if request.request_id in exposure_counts:
            if request.visible_count != exposure_counts[request.request_id]:
                raise ValueError("A restored request has a different exposure count")
            requests.append(request)

    if study.generate_impressions(observe_request=capture) != dataset["rows"]:
        raise ValueError("The regenerated impressions differ from the saved mock dataset")
    if len(requests) != len(exposure_counts):
        raise ValueError("Could not recover the complete test request sequence")
    return requests


def score_candidates(requests, development, test, searches):
    # Prepend the recorded impressions to verify each refit against its saved scores.
    evaluation = list(test)
    slices = {}
    for request in requests:
        start = len(evaluation)
        evaluation.extend({"features": features} for _, features, _ in request.candidates)
        slices[request.request_id] = slice(start, len(evaluation))

    results = {}
    for name, method in MODEL_METHODS.items():
        run = searches["models"][name][method]
        scores = np.asarray(study.fit_and_score(name, development, evaluation, run["parameters"]))
        np.testing.assert_allclose(scores[: len(test)], run["test_scores"], atol=1e-12, rtol=1e-10)
        results[name] = {request_id: scores[span] for request_id, span in slices.items()}
    return results


def shade_from_features(features):
    return study.Shade(
        features["color_family"], features["lightness"], features["chroma"], features["texture"]
    )


def reference_gains(requests, seed):
    rng = np.random.default_rng(seed)
    ideal_gains = np.r_[0, np.cumsum(study.DISCOUNTS)]
    references = {}
    for request in requests:
        profile = study.Profile(request.preferred, request.intent)
        carts = []
        for _, x, _ in request.candidates:
            shade = shade_from_features(x)
            carts.append(
                [
                    study.draw_actions(
                        rng, profile, shade, x["rating_avg"], REFERENCE_RANK, request.intent
                    )[2]
                    for _ in range(RELEVANCE_DRAWS)
                ]
            )
        relevance = np.asarray(carts, dtype=np.int8)
        ideal = ideal_gains[np.minimum(relevance.sum(axis=0), len(study.DISCOUNTS))]
        valid = ideal > 0
        gains = (relevance[:, valid] / ideal[valid]).sum(axis=1)
        references[request.request_id] = (gains, int(valid.sum()))
    return references


def initial_exposures(rows, cutoff):
    history = defaultdict(deque)
    for row in rows:
        requested_at = datetime.fromisoformat(row["requested_at"])
        if cutoff - WINDOW <= requested_at < cutoff:
            group = (row["member"], row["features"]["makeup_zone"])
            history[group].append((requested_at, (row["product_id"], row["shade_id"])))
    return history


def try_on_histories(rows, requests):
    actions = defaultdict(list)
    for row in rows:
        if row["tried_on"] or row["added_to_cart"]:
            group = (row["member"], row["features"]["makeup_zone"])
            actions[group].append((datetime.fromisoformat(row["requested_at"]), row))

    histories = {}
    for request in requests:
        cutoff = request.requested_at - TRY_ON_WINDOW
        earlier = [
            (at, row)
            for at, row in actions[(request.member, request.zone)]
            if at < request.requested_at
        ]
        trials = {
            (row["request_id"], item_key(row))
            for at, row in earlier
            if at >= cutoff and row["tried_on"]
        }
        counts = Counter(key for _, key in sorted(trials))
        carted = {item_key(row) for _, row in earlier if row["added_to_cart"]}
        repeat_candidates = {
            key
            for key, _, _ in request.candidates
            if counts[key] >= MIN_TRY_ONS_TO_RESHOW and key not in carted
        }
        histories[request.request_id] = TryOnHistory(counts, carted, repeat_candidates)
    return histories


def select_unseen_chips(request, scores, last_seen, indices, *, eligible=None):
    candidates = request.candidates
    if eligible is None:
        eligible = range(len(candidates))
    unseen = [i for i in eligible if candidates[i][0] not in last_seen]
    fresh = study.top_chips(
        [candidates[i] for i in unseen], [scores[i] for i in unseen], request.personalized
    )
    selected = [indices[row[0]] for row in fresh]
    if len(selected) < 3:
        products = {row[0][0] for row in fresh}
        previously_seen = sorted(
            (i for i in eligible if candidates[i][0] in last_seen),
            key=lambda i: (last_seen[candidates[i][0]], -scores[i]),
        )
        for i in previously_seen:
            product = candidates[i][0][0]
            if product in products:
                continue
            selected.append(i)
            products.add(product)
            if len(selected) == 3:
                break
    return selected


def select_try_on_chips(request, scores, last_seen, indices, history):
    candidates = request.candidates
    shades = [shade_from_features(features) for _, features, _ in candidates]
    tried_shades = [
        (shades[indices[key]], count) for key, count in history.counts.items() if key in indices
    ]
    selection_scores = scores
    if tried_shades:
        order = sorted(range(len(scores)), key=lambda i: -scores[i])
        model_percentiles = np.empty(len(scores))
        model_percentiles[order] = np.linspace(1.0, 0.0, len(scores))
        trial_count = sum(count for _, count in tried_shades)
        affinities = np.array(
            [
                sum(study.style_match(prior, shade) * count for prior, count in tried_shades)
                / trial_count
                for shade in shades
            ]
        )
        model_weight = 1 - TRY_ON_AFFINITY_WEIGHT
        selection_scores = model_weight * model_percentiles + TRY_ON_AFFINITY_WEIGHT * affinities

    new = [
        i
        for i, (key, _, _) in enumerate(candidates)
        if key not in history.counts and key not in history.carted
    ]
    selected = select_unseen_chips(request, selection_scores, last_seen, indices, eligible=new)
    products = {candidates[i][0][0] for i in selected[:2]}
    families = {shades[i].family for i in selected[:2]}
    repeat = max(
        (
            i
            for i, (key, _, _) in enumerate(candidates)
            if key in history.repeat_candidates and key[0] not in products
        ),
        key=lambda i: (shades[i].family not in families, scores[i]),
        default=None,
    )
    return selected if repeat is None else [*selected[:2], repeat]


def select_chips(request, scores, last_seen, policy, try_on_history=None):
    candidates = request.candidates
    indices = {row[0]: i for i, row in enumerate(candidates)}
    baseline = study.top_chips(candidates, scores, request.personalized)
    original = [indices[row[0]] for row in baseline]
    if policy == "try_on":
        return select_try_on_chips(request, scores, last_seen, indices, try_on_history), original
    if policy == "all":
        return select_unseen_chips(request, scores, last_seen, indices), original
    if policy == "before" or len(baseline) < 3 or baseline[2][0] not in last_seen:
        return original, original

    products = {row[0][0] for row in baseline[:2]}
    families = {row[1]["color_family"] for row in baseline[:2]}
    eligible = [
        i
        for i, (key, _, _) in enumerate(candidates)
        if key[0] not in products and key not in last_seen
    ]
    if not eligible:
        return original, original
    # Prefer the same color-family diversity as the third slot of top_chips.
    selected = original.copy()
    selected[2] = max(
        eligible, key=lambda i: (candidates[i][1]["color_family"] not in families, scores[i])
    )
    return selected, original


def replay(requests, scores, references, initial, *, policy, try_on_contexts=None):
    history = defaultdict(deque, {key: deque(values) for key, values in initial.items()})
    records = []
    for request in requests:
        history_key = (request.member, request.zone)
        recent = history[history_key]
        cutoff = request.requested_at - WINDOW
        while recent and recent[0][0] < cutoff:
            recent.popleft()
        last_seen = {key: at for at, key in recent}
        try_on_history = (
            try_on_contexts[request.request_id] if try_on_contexts is not None else None
        )
        selected, baseline = select_chips(
            request, scores[request.request_id], last_seen, policy, try_on_history
        )
        slate = [request.candidates[i][0] for i in selected]
        shown = slate[: request.visible_count]
        repeated = sum(key in last_seen for key in shown)
        recent.extend((request.requested_at, key) for key in shown)

        gains, valid_draws = references[request.request_id]
        ndcg_sum = float(gains[selected] @ study.DISCOUNTS[: len(selected)])
        record = {
            "request_id": request.request_id,
            "member": request.member,
            "zone": request.zone,
            "requested_at": request.requested_at.isoformat(),
            "slate": [list(key) for key in slate],
            "visible_count": len(shown),
            "previously_seen": bool(last_seen),
            "repeated_impressions": repeated,
            "unique_colors_7d": len(set(last_seen).union(shown)),
            "rotated": selected != baseline,
            "visible_rotation": selected[: request.visible_count]
            != baseline[: request.visible_count],
            "ndcg_sum": ndcg_sum,
            "relevance_draws_with_positive": valid_draws,
        }
        if try_on_history is not None:
            repeated_try_on = next(
                (key for key in slate if key in try_on_history.repeat_candidates), None
            )
            record.update(
                prior_try_ons=try_on_history.counts.total(),
                repeat_try_on_candidates=len(try_on_history.repeat_candidates),
                reshown_try_on=list(repeated_try_on) if repeated_try_on else None,
                reshown_try_on_visible=repeated_try_on in shown,
            )
        records.append(record)

    impressions = sum(row["visible_count"] for row in records)
    repeats = sum(row["repeated_impressions"] for row in records)
    summary = {
        "ndcg_at_3": sum(row["ndcg_sum"] for row in records)
        / sum(row["relevance_draws_with_positive"] for row in records),
        "mean_unique_colors_7d": sum(row["unique_colors_7d"] for row in records) / len(records),
        "repeat_exposure_rate": repeats / impressions,
        "repeated_impressions": repeats,
        "impressions": impressions,
        "requests_with_previous_exposures": sum(row["previously_seen"] for row in records),
        "rotated_requests": sum(row["rotated"] for row in records),
        "visible_rotations": sum(row["visible_rotation"] for row in records),
        "requests": records,
    }
    if try_on_contexts is not None:
        summary.update(
            requests_with_try_on_history=sum(row["prior_try_ons"] > 0 for row in records),
            requests_with_repeat_try_on_candidates=sum(
                row["repeat_try_on_candidates"] > 0 for row in records
            ),
            reshown_try_on_requests=sum(row["reshown_try_on"] is not None for row in records),
            visible_reshown_try_on_requests=sum(row["reshown_try_on_visible"] for row in records),
        )
    return summary


def plot_comparison(results, path, request_count, impression_count, *, include_try_on=False):
    font_path = Path("C:/Windows/Fonts/malgun.ttf")
    font = FontProperties(fname=font_path) if font_path.is_file() else None
    captions = (
        (
            "추천 칩 순환 범위 비교",
            "시착 이력 반영 추천 비교",
            "순환 없음",
            "1개 순환",
            "3개 순환",
            "시착 이력 반영",
            "7일 고유 노출 색상 수",
            "반복 노출률",
        )
        if font
        else (
            "Palette chip rotation",
            "Try-on history in palette recommendations",
            "No rotation",
            "One chip",
            "Three chips",
            "Try-on history",
            "7-day unique colors",
            "Repeat exposure",
        )
    )
    rotation_title, try_on_title, *policy_labels, unique_colors, repeats = captions
    before, after, all_chips, try_on = policy_labels
    title = try_on_title if include_try_on else rotation_title
    labels_and_colors = {
        "before": (before, "#8297aa"),
        "after": (after, "#17796f"),
        "all": (all_chips, "#3c558b"),
        "try_on": (try_on, "#17796f"),
    }
    chart_policies = ("before", "all", "try_on") if include_try_on else ROTATION_POLICIES
    fig = Figure(figsize=(13.4, 4.5), facecolor="white")
    FigureCanvasAgg(fig)
    axes = fig.subplots(1, 3)
    fig.subplots_adjust(left=0.069, right=0.97, bottom=0.19, top=0.74, wspace=0.37)
    fig.text(0.067, 0.93, title, fontsize=17, color="#142c3c", fontproperties=font)
    subtitle = (
        f"목업 재생 · 동일 추천 요청 {request_count}건과 노출 {impression_count}건"
        if font
        else f"Mock replay with {request_count} requests and {impression_count} exposures"
    )
    fig.text(0.068, 0.855, subtitle, fontsize=9, color="#4d6273", fontproperties=font)
    metrics = (
        ("ndcg_at_3", "NDCG@3", lambda v: f"{v:.4f}"),
        ("mean_unique_colors_7d", unique_colors, lambda v: f"{v:.2f}"),
        ("repeat_exposure_rate", repeats, lambda v: f"{v:.2%}"),
    )
    labels = ("Classifier\n+ Optuna", "PairLogit\n+ RandomSearch")
    positions = np.arange(len(labels))
    for ax, (metric, label, format_value) in zip(axes, metrics, strict=True):
        maximum = max(
            values[policy][metric] for values in results.values() for policy in chart_policies
        )
        ax.set_title(label, fontsize=12, pad=13, color="#142c3c", fontproperties=font)
        ax.set_ylim(0, max(maximum * 1.23, 0.02))
        ax.set_xticks(positions, labels, fontsize=9, color="#243d4d")
        ax.yaxis.set_major_locator(MaxNLocator(4))
        if metric == "repeat_exposure_rate":
            ax.yaxis.set_major_formatter(PercentFormatter(xmax=1.0, decimals=0))
        ax.grid(axis="y", color="#e3e9ee", linewidth=0.8)
        ax.set_axisbelow(True)
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.spines["bottom"].set_color("#a9b7c2")
        ax.tick_params(axis="both", length=0, labelcolor="#405564")
        for offset, policy in zip((-0.29, 0, 0.29), chart_policies, strict=True):
            caption, color = labels_and_colors[policy]
            values = [row[policy][metric] for row in results.values()]
            bars = ax.bar(positions + offset, values, 0.23, color=color, label=caption)
            ax.bar_label(
                bars,
                labels=[format_value(v) for v in values],
                padding=4,
                fontsize=8,
                color="#122c3d",
            )
    fig.legend(
        *axes[0].get_legend_handles_labels(),
        loc="upper right",
        bbox_to_anchor=(0.967, 0.95),
        ncol=3,
        frameon=False,
        prop=font,
    )
    fig.savefig(path, dpi=180)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_run", type=Path, help="Original mock dataset and result directory")
    parser.add_argument("search_run", type=Path, help="Hyperparameter comparison directory")
    parser.add_argument("output", type=Path, help="Run directory")
    parser.add_argument("--update-existing", action="store_true", help="Extend the saved replay")
    args = parser.parse_args()
    previous = None
    if args.update_existing:
        if not (args.output / "results.json").is_file():
            parser.error("the saved rotation results are required to update an existing run")
        previous = study.read_json(args.output / "results.json")
    elif args.output.exists():
        parser.error("choose a new output directory")
    base, train, validation, test = load_holdout(args.base_run)
    dataset = study.read_json(args.base_run / "dataset.json")
    searches = study.read_json(args.search_run / "results.json")
    fields = ("dataset_sha256", "cutoffs", "test_impression_ids")
    if any(base[field] != searches[field] for field in fields):
        raise ValueError("The saved search run uses a different holdout")

    requests = restore_requests(dataset, test)
    print(f"Restored {len(requests)} requests and their eligible candidate pools", flush=True)
    scores = score_candidates(requests, train + validation, test, searches)
    print("Both model refits matched the saved scores on recorded impressions", flush=True)
    reference_seed = base["seed"] + 1
    references = reference_gains(requests, reference_seed)
    initial = initial_exposures(dataset["rows"], requests[0].requested_at)
    try_on_contexts = try_on_histories(dataset["rows"], requests)
    results = {
        name: {
            policy: replay(
                requests,
                scores[name],
                references,
                initial,
                policy=policy,
                try_on_contexts=try_on_contexts if policy == "try_on" else None,
            )
            for policy in POLICIES
        }
        for name in MODEL_METHODS
    }

    settings = {
        "base_run": args.base_run.as_posix(),
        "search_run": args.search_run.as_posix(),
        "models": {
            name: {"method": method, "parameters": searches["models"][name][method]["parameters"]}
            for name, method in MODEL_METHODS.items()
        },
        "dataset_sha256": base["dataset_sha256"],
        "test_impression_ids": base["test_impression_ids"],
        "test_requests": len(requests),
        "test_requests_with_three_exposures": sum(r.visible_count == 3 for r in requests),
        "candidate_counts": {r.request_id: len(r.candidates) for r in requests},
        "lookback_days": WINDOW.days,
        "relevance_draws_per_request": RELEVANCE_DRAWS,
        "reference_rank": REFERENCE_RANK,
        "reference_seed": reference_seed,
    }
    if previous is not None:
        if any(previous[key] != value for key, value in settings.items()):
            raise ValueError("The replay settings differ from the saved run")
        for name in MODEL_METHODS:
            for policy, saved in previous["results"][name].items():
                if policy in ROTATION_POLICIES and saved != results[name][policy]:
                    raise ValueError(f"The saved {name} {policy} result could not be reproduced")
        print("Reproduced the saved rotation conditions for both models", flush=True)

    settings["try_on_policy"] = {
        "lookback_days": TRY_ON_WINDOW.days,
        "min_distinct_try_on_requests_to_reshow": MIN_TRY_ONS_TO_RESHOW,
        "try_on_affinity_weight": TRY_ON_AFFINITY_WEIGHT,
        "reshow_slot": 3,
    }

    args.output.mkdir(parents=True, exist_ok=args.update_existing)
    report_dir = args.output / "report"
    report_dir.mkdir(exist_ok=args.update_existing)
    charts = {"comparison.png": False, "try-on-comparison.png": True}
    temporary_plots = {}
    try:
        for name, include_try_on in charts.items():
            with NamedTemporaryFile(dir=report_dir, suffix=".png", delete=False) as file:
                temporary_plots[name] = Path(file.name)
            plot_comparison(
                results,
                temporary_plots[name],
                len(requests),
                len(test),
                include_try_on=include_try_on,
            )
        study.write_json(
            args.output / "results.json", {**(previous or {}), **settings, "results": results}
        )
        for name, temporary in temporary_plots.items():
            os.replace(temporary, report_dir / name)
    finally:
        for temporary in temporary_plots.values():
            temporary.unlink(missing_ok=True)
    for name, policies in results.items():
        for policy, summary in policies.items():
            print(name, policy, {key: val for key, val in summary.items() if key != "requests"})


if __name__ == "__main__":
    main()
