# ML experiments

Experiment outputs are grouped by run under `ml/runs/`. Each experiment folder keeps its configuration, data manifest, logs, checkpoints and a `report/` directory with the report and figures. Shared datasets and reusable training code remain in `ml/data/` and `ml/src/`.

The run outputs are local and ignored by Git because they include large artifacts. This index is tracked so the structure remains discoverable.

## Smartphone pore experiments

| Experiment | Local run directory |
|---|---|
| Fixed texture preprocessing | [`pore-texture-unsharp-20261028`](runs/pore-texture-unsharp-20261028/) |
| Unsharp 75 + contrast 40 | [`pore-unsharp75-contrast40-20261028`](runs/pore-unsharp75-contrast40-20261028/) |
| 100k augmentation data | [`pore-aug100k-20261028`](runs/pore-aug100k-20261028/) |
| 100k augmentation training | [`pore-aug100k-b32-e100-20261028`](runs/pore-aug100k-b32-e100-20261028/) |
| RunPod training | [`pore-runpod-20261028`](runs/pore-runpod-20261028/) |
| Paper-style four splits | [`pore-paper-splits-20261028`](runs/pore-paper-splits-20261028/) |
| Backbone comparison preparation | [`pore-backbone-original-20261028`](runs/pore-backbone-original-20261028/) |
| Image quality audit | [`pore-image-quality-audit-20261028`](runs/pore-image-quality-audit-20261028/) |
| ROI visual inspection | [`pore-roi-inspection-20261028`](runs/pore-roi-inspection-20261028/) |
| Historical experiment overview | [`pore-experiment-overview-20261028`](runs/pore-experiment-overview-20261028/) |

Older ROI selection, oversampling and regression comparisons are grouped by condition under [`batch-diversity-ablation-20261027`](runs/batch-diversity-ablation-20261027/). Their corresponding report and figures are stored in each condition's `report/` folder.
