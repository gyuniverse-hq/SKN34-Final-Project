# Lip naturalness learner (offline)

Frozen ResNet18 (ImageNet) lip-crop embeddings + linear heads.
Labels: R5 checklist absolute scores (packs 01–03, n=98) and R5 A/B pairs (v3).
Face-level GroupKFold. Defect names are never features. Research only — not in the app.

## Absolute score (Ridge)

- n=98 images / 58 faces, 5-fold
- CV Spearman **0.314**, MAE **1.379** (mean baseline MAE 1.320)
- label mean 3.13 ± 1.60

By kind (out-of-fold):

| kind | n | label mean | pred mean | Spearman | MAE |
|---|---:|---:|---:|---:|---:|
| real | 6 | 4.80 | 3.54 | 0.135 | 1.255 |
| render | 87 | 3.19 | 3.10 | 0.211 | 1.379 |
| sticker | 5 | 0.00 | 0.06 | — | 1.517 |

## Pairwise preference (Logistic on emb_left − emb_right)

- n=476 decisive pairs / 52 faces (ties skipped), 5-fold
- CV accuracy **0.809** (majority baseline 0.536)

## Reading

- Pairwise is the usable signal: same-face current vs defect ranking is learnable (~81% vs ~54% majority).
- Absolute totals are only weakly tracked (Spearman ~0.31; MAE ≈ mean baseline). Do not use as a 0–5 judge yet.
- Sticker crops separate in predicted means; fine render ranking needs the pairwise head (or more absolute labels).
- Next: use pairwise scores to rank renderer/defect edits on held-out faces, then fix the weakest lip cues in the renderer.
