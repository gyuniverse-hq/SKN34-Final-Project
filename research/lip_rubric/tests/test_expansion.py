import sys
import json
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from expand_pack import build, select_new
from expansion_scores import summarize
from common import checks, load_json


def row(face, label='bare', reviewed='yes'):
    return {'face_id': face, 'detected': '1', 'human_label': label, 'identity_reviewed': reviewed}


def test_new_faces_exclude_original_and_practice_and_require_review():
    candidates = [row('old'), row('practice'), row('new'), row('new'), row('unchecked', reviewed='')]
    assert [r['face_id'] for r in select_new(candidates, [{'face_id': 'old'}],
                                             {'practice_sources': [{'face_id': 'practice'}]})] == ['new']


def test_conflicting_labels_for_identity_are_rejected():
    with pytest.raises(ValueError, match='충돌'):
        select_new([row('same'), row('same', 'lipstick')], [], {'practice_sources': []})


def test_output_must_stay_in_research_data(tmp_path):
    with pytest.raises(ValueError, match='Git 제외'):
        build(tmp_path / 'out', 1)


def test_score_bands_require_enough_people_and_exclude_repeats():
    rubric = load_json(HERE / 'rubric.json')
    yes = json.dumps({c['id']: '1' for c in checks(rubric)})
    images = [dict(image_id='a', face_id='face', split='pool', kind='render', finish='satin',
                   repeat_of='', pack_id='pack', tuning_json='{}'),
              dict(image_id='b', face_id='face', split='pool', kind='render', finish='satin',
                   repeat_of='a', pack_id='pack', tuning_json='{}'),
              dict(image_id='c', face_id='other', split='test', kind='render', finish='matte',
                   repeat_of='', pack_id='pack', tuning_json='{}')]
    ratings = [dict(image_id='a', checks_json=yes), dict(image_id='a', checks_json=yes),
               dict(image_id='b', checks_json=yes), dict(image_id='c', checks_json=yes)]
    rows, bands = summarize(images, ratings, rubric, minimum_raters=2)
    assert len(rows) == 2 and rows[0]['total_mean'] == 5 and rows[0]['band'] == '4-5'
    assert rows[1]['rater_count'] == 1 and rows[1]['total_mean'] == ''
    assert bands == {'render 4-5': 1}
