"""Renderer settings that spread lip quality from 'current renderer' down to 'almost a sticker'.

These are design levels for sampling, not labels: the human rating is the label.
Values are TUNING overrides for components/ar/faceTrackerHtml.ts (see research/lip_texture/render.py).
Measured 2026-11-14 on three LaPa faces: the page compensates (measured blur, light), so even L1 changes only a small
part of the lip and D4_edge changes no pixel. build_v3.py therefore uses image-space defects (degrade.py) instead.
"""

LADDER = {
    'L5_current': {},
    'L4_less_texture': {'creaseGain': 0.5, 'hlSparkle': 0},
    'L3_flat_shade': {'creaseGain': 0.25, 'hlSparkle': 0, 'opaqueShadeGamma': 0.3},
    'L2_hard_edge': {'creaseGain': 0.25, 'hlSparkle': 0, 'opaqueShadeGamma': 0.3, 'lipFeatherPx': 0, 'lipEdgePx': 0},
    'L1_near_sticker': {'creaseGain': 0, 'hlSparkle': 0, 'opaqueShadeGamma': 0, 'hlKeep': [0, 0], 'glossGain': 0,
                        'lipSheen': 0, 'lipFeatherPx': 0, 'lipEdgePx': 0},
}

# One rubric question broken on purpose, the rest left at the current renderer.
DEFECTS = {
    'D1_texture': {'creaseGain': 0, 'hlSparkle': 0},
    'D2_shading': {'opaqueShadeGamma': 0, 'lightMatch': False},
    'D3_gloss': {'glossGain': 8, 'glossCavity': 0, 'lipSheen': 1.0},
    'D4_edge': {'lipFeatherPx': 0, 'lipEdgePx': 0},
    'D5_fit': {'opaqueShadeGamma': 0, 'lipFill': 3, 'blurMax': 0},
}

VARIANTS = {**LADDER, **DEFECTS}
