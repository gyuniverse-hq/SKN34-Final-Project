import hashlib
import json
import logging
from datetime import UTC, datetime
from uuid import uuid4

from starlette.concurrency import run_in_threadpool

from app.core.ar_palette import FEATURE_VERSION, score_inputs, shade_features, top_chips
from app.core.ar_palette_artifacts import load_palette_model, score_model, write_json
from app.core.errors import ApiError
from app.schemas.ar_history import Candidate, RankedPalette

logger = logging.getLogger(__name__)


def experiment_arm(experiment, member_id):
    digest = hashlib.sha256(f"{experiment}:{member_id}".encode()).digest()
    return "B" if digest[0] % 2 else "A"


def model_scores(settings, rows, model_dir=None):
    model_dir = model_dir if model_dir is not None else settings.ar_palette_model_dir
    if model_dir is None:
        raise ValueError("AR model directory is missing")
    local = settings.env in ("local", "development", "test")
    model, version, source = load_palette_model(
        model_dir.resolve(),
        allow_synthetic=local,
        require_offline_pass=not local,
    )
    prefix = "s" if source == "synthetic" else "m"
    return score_model(model, [row[1] for row in rows]), f"{prefix}-{version}"


class ArPaletteService:
    def __init__(self, repository, settings):
        self.repo = repository
        self.settings = settings

    async def rank(self, owner, body):
        saved = await self.repo.lock_rank(body.request_id)
        if saved:
            if (saved.member_id, saved.session_id, saved.makeup_zone) != (
                owner,
                body.session_id,
                body.makeup_zone,
            ) or not saved.policy_version.startswith("ar1:"):
                raise ApiError(409, "AR history identity conflict", "ar_history_conflict")
            candidates = await self.repo.rank_candidates(body.request_id)
            visible = {(item.product_id, item.shade_id) for item in body.shades}
            if any((item.product_id, item.shade_id) not in visible for item in candidates):
                raise ApiError(409, "AR palette changed", "ar_history_conflict")
            return RankedPalette(request_id=body.request_id, candidates=candidates)

        now = datetime.now(UTC)
        colors, ratings, daily = await self.repo.ranking_inputs(owner, body.makeup_zone, now)
        catalog = {key: shade for key, data in colors.items() if (shade := shade_features(*data))}
        order = [(item.product_id, item.shade_id) for item in body.shades]
        rows, personalized = score_inputs(body.makeup_zone, order, catalog, ratings, daily)
        mode = self.settings.ar_palette_mode
        experiment = self.settings.ar_palette_experiment if mode == "experiment" else None
        if mode == "experiment" and not experiment:
            raise ApiError(503, "AR experiment is not configured", "ar_experiment_unavailable")
        arm = experiment_arm(experiment, owner) if experiment else "-"
        control_model = self.settings.ar_palette_baseline_model_dir if arm == "A" else None
        served = "rule"
        strategy = "personalized" if personalized else "rating"
        scores = [row[2] for row in rows]
        if rows and (mode == "model" or arm == "B" or control_model is not None):
            try:
                scores, served = await run_in_threadpool(
                    model_scores, self.settings, rows, control_model
                )
                strategy = "ml"
            except Exception:
                served = "fallback"
                logger.warning("AR palette inference fallback")
        elif not rows:
            served = "empty"
        selected = top_chips(rows, scores, personalized)
        candidates = [
            Candidate(candidate_id=uuid4(), product_id=key[0], shade_id=key[1])
            for key, _, _ in selected
        ]
        policy = f"ar1:{experiment or '-'}:{arm}:{served}"
        if candidates:
            payload = {
                "feature_version": FEATURE_VERSION,
                "requested_at": now.isoformat(),
                "policy_version": policy,
                "catalog_digest": hashlib.sha256(
                    json.dumps(
                        [(key, colors[key], ratings.get(key[0])) for key in sorted(colors)],
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest(),
                "features": {
                    str(candidate.candidate_id): features
                    for candidate, (_, features, _) in zip(candidates, selected, strict=True)
                },
            }
            try:
                await run_in_threadpool(
                    write_json,
                    self.settings.ar_palette_data_dir / "snapshots" / f"{body.request_id}.json",
                    payload,
                )
            except OSError:
                logger.warning("AR palette feature snapshot write failed")
        await self.repo.save_rank(body, owner, now, strategy, policy, candidates)
        return RankedPalette(request_id=body.request_id, candidates=candidates)
