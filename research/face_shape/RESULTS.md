# Face-shape classifier (offline calibration)

Data: Roboflow Universe `ashish-workspace/face-shape-classification-yoqx4-lfvhe` v1, CC BY 4.0 (page lists no image provenance or consent; images stay in git-ignored `research/data/`, only the fitted numbers are committed).
Frontal photos kept (yaw 0.85-1.18, roll <= 10 deg): 3816 of 4002. Labels are the uploader's, not a clinical standard.

Model: standardise + multinomial logistic regression, C=3 (chosen on valid), refit on train+valid.

- test accuracy **0.609** (n=386; chance by majority class 0.225), top-2 0.855
- 5-fold CV on train+valid 0.595 +- 0.009
- mean max probability on test 0.614

Confusion matrix (rows = label, columns = prediction):

| | Round | Square | Oblong | Heart | Oval |
|---|---|---|---|---|---|
| Round | 42 | 13 | 1 | 1 | 7 |
| Square | 8 | 54 | 3 | 2 | 9 |
| Oblong | 1 | 4 | 67 | 5 | 6 |
| Heart | 6 | 4 | 13 | 44 | 9 |
| Oval | 17 | 4 | 9 | 29 | 28 |

Standardised weights per class (rows) and feature (columns):

| | faceLong | cheekWide | foreheadW | jawEarW | chinW | jawAngle | jawCurve | chinAngle |
|---|---|---|---|---|---|---|---|---|
| Round | -2.12 | +1.47 | +0.19 | +1.14 | +0.34 | -0.85 | -0.20 | -0.32 |
| Square | -1.21 | -0.74 | +0.68 | +0.42 | -0.41 | -0.82 | -0.57 | +0.45 |
| Oblong | +3.05 | -0.77 | -1.09 | -1.14 | +0.22 | +0.64 | +0.16 | +0.25 |
| Heart | +0.15 | -0.20 | +0.48 | -0.15 | -0.16 | +0.83 | +0.48 | -0.18 |
| Oval | +0.13 | +0.24 | -0.26 | -0.28 | +0.01 | +0.20 | +0.13 | -0.19 |

Read as: a measured estimate with a probability, not a diagnosis. The app shows the top class with its probability and blends the shading rules by probability.
