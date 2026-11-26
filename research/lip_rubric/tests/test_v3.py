import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(HERE))
from build_pack import LIPS_INNER, LIPS_OUTER
from build_v3 import OTHER_DEFECTS, plan
from degrade import DEFECTS, LEVELS, apply, lip_mask


def synthetic_page(width=720):
    page = {'x': [0.0] * 478, 'y': [0.0] * 478}
    for indices, rx, ry in ((LIPS_OUTER, 120, 50), (LIPS_INNER, 40, 10)):
        for j, i in enumerate(indices):
            a = 2 * np.pi * j / len(indices)
            page['x'][i] = width - 1 - (360 + rx * np.cos(a)); page['y'][i] = 600 + ry * np.sin(a)
    return page


@pytest.mark.parametrize('defect', list(DEFECTS))
def test_defects_change_lips_but_not_far_skin(defect):
    rng = np.random.default_rng(0)
    off = np.full((960, 720, 3), 170, np.uint8)
    render = off.copy(); page = synthetic_page()
    hard, _, _, _ = lip_mask(page, render.shape)
    render[hard] = [40, 40, 180]
    render = np.clip(render.astype(int) + rng.integers(-20, 20, render.shape), 0, 255).astype(np.uint8)
    out = apply(render, off, page, '#C8102E', defect, LEVELS['strong'], seed=1)
    assert out.shape == render.shape and out.dtype == np.uint8
    diff = np.abs(out.astype(int) - render.astype(int)).sum(2)
    assert diff[hard].mean() > 1 or defect in ('edge_spill', 'edge_gap', 'misalign')
    assert diff[:300].max() == 0 and diff[:, :100].max() == 0


def test_strength_orders_sticker_blend():
    off = np.full((960, 720, 3), 170, np.uint8); page = synthetic_page()
    hard, _, _, _ = lip_mask(page, off.shape)
    render = off.copy(); render[hard] = [60, 60, 200]
    render[hard] = np.clip(render[hard].astype(int) + np.random.default_rng(1).integers(-30, 30, render[hard].shape), 0, 255)
    gaps = [np.abs(apply(render, off, page, '#C8102E', 'sticker_blend', LEVELS[k]).astype(int) - render.astype(int))[hard].mean() for k in ('light', 'mild', 'strong')]
    assert gaps[0] < gaps[1] < gaps[2]


def test_plan_balances_defects():
    rows = [{'lapa_stem': f's{i}', 'face_id': f'f{i}'} for i in range(16)]
    items = plan(rows, seed=1)
    assert all(len(it['variants']) == 5 and it['variants'][0] == ('current', '') for it in items)
    assert all(sum(v[0] == 'sticker_blend' for v in it['variants']) == 1 for it in items)
    counts = Counter(v[0] for it in items for v in it['variants'] if v[0] in OTHER_DEFECTS)
    assert max(counts.values()) - min(counts.values()) <= 1
    assert len({it['shade'] for it in items}) == 5


def test_ab_summary_consistency_and_scores():
    from ab_results import summarize
    key = {
        'ab1': {'pair_id': 'ab1', 'left': 'c', 'right': 'd', 'face_id': 'f', 'split': 'pool', 'left_variant': 'current', 'left_level': '',
                'right_variant': 'sticker_blend', 'right_level': 'strong', 'repeat_of': ''},
        'ab2': {'pair_id': 'ab2', 'left': 'd', 'right': 'c', 'face_id': 'f', 'split': 'pool', 'left_variant': 'sticker_blend', 'left_level': 'strong',
                'right_variant': 'current', 'right_level': '', 'repeat_of': 'ab1'},
        'ab3': {'pair_id': 'ab3', 'left': 'c', 'right': 'e', 'face_id': 'f', 'split': 'pool', 'left_variant': 'current', 'left_level': '',
                'right_variant': 'texture_loss', 'right_level': 'light', 'repeat_of': ''},
    }
    answers = {'ab1': {'choice': 'left'}, 'ab2': {'choice': 'right'}, 'ab3': {'choice': 'same'}}
    s, bt, _ = summarize(key, answers)
    assert s['repeat_consistency'] == 1 and s['current_vs_defect']['sticker_blend:strong']['current_wins'] == 1
    assert s['current_vs_defect']['texture_loss:light']['same'] == 1 and bt['c'] > bt['d']


def test_ab_template_placeholders():
    html = (HERE / 'rating/ab.html').read_text(encoding='utf8')
    assert html.count('__PAIRS__') == 1 and html.count('__PACK__') == 1 and 'http' not in html
