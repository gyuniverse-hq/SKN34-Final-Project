"""Reusable condition checks retained from archived experiments."""

from .sam import optimization_spec


def require_one_factor(settings, baseline, variant):
    def normalize(value):
        return dict(
            freeze_bn_stats=False,
            finetune_scope="all",
            **{
                k: v
                for k, v in value.items()
                if k not in ("output", "record_train_metrics", "freeze_bn_stats", "finetune_scope")
            },
        ) | {k: value[k] for k in ("freeze_bn_stats", "finetune_scope") if k in value}

    expected = normalize(baseline)
    if variant == "bn_stats_frozen":
        expected["freeze_bn_stats"] = True
    elif variant == "layer4_only":
        expected["finetune_scope"] = "layer4"
    else:
        raise ValueError("Unknown ablation variant")
    if normalize(settings) != expected or settings.get("record_train_metrics") is not True:
        raise ValueError(
            "Ablation requires exactly one predefined treatment; other settings unchanged"
        )


def require_ordinal_loss_only(candidate, baseline):
    excluded = {"output", "loss"}
    if (
        {k: v for k, v in candidate.items() if k not in excluded}
        != {k: v for k, v in baseline.items() if k not in excluded}
        or baseline.get("loss", "weighted_cross_entropy") != "weighted_cross_entropy"
        or candidate.get("loss") != "weighted_ordinal_cdf"
        or candidate.get("optimizer") != "sam_adamw"
    ):
        raise ValueError("Only weighted CE -> weighted ordinal CDF may change")


def require_sam_settings(candidate, baseline):
    excluded = {"output", "record_train_metrics", "optimizer", "sam_rho"}
    if (
        {k: v for k, v in candidate.items() if k not in excluded}
        != {k: v for k, v in baseline.items() if k not in excluded}
        or baseline.get("optimizer", "adamw") != "adamw"
        or candidate.get("optimizer") != "sam_adamw"
        or candidate.get("sam_rho") != 0.05
        or candidate.get("record_train_metrics") is not True
    ):
        raise ValueError("SAM must be the only treatment; keep baseline training settings")
    return optimization_spec(candidate)


def require_weighted_focal_only(candidate, baseline):
    excluded = {"output", "loss", "focal_gamma"}
    if (
        {k: v for k, v in candidate.items() if k not in excluded}
        != {k: v for k, v in baseline.items() if k not in excluded}
        or baseline.get("loss", "weighted_cross_entropy") != "weighted_cross_entropy"
        or candidate.get("loss") != "weighted_focal"
        or candidate.get("optimizer") != "sam_adamw"
        or candidate.get("focal_gamma") != 2.0
    ):
        raise ValueError("Only WCE -> WFL gamma=2 may change")
