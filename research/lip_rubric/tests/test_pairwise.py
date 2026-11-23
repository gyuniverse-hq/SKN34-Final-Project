import json
import sys
from pathlib import Path

import pytest
from PIL import Image

HERE = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(HERE))
from common import load_json, read_csv, write_csv
from pairwise import MockPairJudge, analyze, build_pairs, decide, parse_choice, public_rows, run


def synthetic():
    images, per = {}, {}
    for f in range(8):
        for s, shade in enumerate(('glossy_red', 'satin_red')):
            i = f'r{f}{s}'
            images[i] = {'image_id': i, 'kind': 'render', 'face_id': f'f{f}', 'shade': shade, 'finish': shade.split('_')[0], 'mouth': 'closed'}
            per[i] = {f'R{r}': min(5.0, f * 0.6 + s * 0.2 + r * 0.05) for r in range(1, 6)}
    images['s0'] = {'image_id': 's0', 'kind': 'sticker', 'face_id': 'f0', 'shade': 'glossy_red', 'finish': 'glossy', 'mouth': 'closed'}
    per['s0'] = {f'R{r}': 0.0 for r in range(1, 6)}
    images['l0'] = {'image_id': 'l0', 'kind': 'real', 'face_id': 'f9', 'shade': '', 'finish': 'satin', 'mouth': 'open'}
    per['l0'] = {f'R{r}': 5.0 for r in range(1, 6)}
    return images, per


def test_build_pairs_kinds_and_truth():
    images, per = synthetic()
    pairs = build_pairs(images, per, mdc=1.0)
    kinds = {p['kind'] for p in pairs}
    assert {'same_face', 'sticker_vs_render', 'real_vs_render', 'cross_face'} <= kinds
    assert all(images[p['left']]['face_id'] != images[p['right']]['face_id'] for p in pairs if p['kind'] == 'cross_face')
    assert all(p['clear'] for p in pairs if p['kind'] == 'cross_face')
    sticker = next(p for p in pairs if p['kind'] == 'sticker_vs_render')
    assert sticker[sticker['human_pref']] != 's0'
    assert [p['pair_id'] for p in pairs] == [p['pair_id'] for p in build_pairs(images, per, mdc=1.0)]
    assert 'human_pref' not in public_rows(pairs)[0] and 'rater_votes' not in public_rows(pairs)[0]


def test_parse_choice():
    assert parse_choice('```json\n{"choice":"B","confidence":4,"reason":"주름이 살아 있음"}\n```')['choice'] == 'B'
    for bad in ('{"choice":"C","confidence":3,"reason":"x"}', '{"choice":"A","confidence":0,"reason":"x"}', '선택할 수 없습니다'):
        with pytest.raises(ValueError):
            parse_choice(bad)


def make_pack(tmp, pairs):
    pack = tmp / 'pack'; (pack / 'images').mkdir(parents=True)
    for p in pairs:
        for i in (p['left'], p['right']):
            for suffix in ('full', 'crop'):
                Image.new('RGB', (4, 4)).save(pack / 'images' / f'{i}_{suffix}.png')
    write_csv(pack / 'pairs.csv', public_rows(pairs))
    return pack


def test_run_resume_and_analyze(tmp_path):
    images, per = synthetic()
    pairs = build_pairs(images, per, mdc=1.0)
    pack = make_pack(tmp_path, pairs)
    config = load_json(HERE / 'judges.json'); out = tmp_path / 'results.csv'
    first = MockPairJudge()
    run(pack, out, config, first, mock=True)
    assert first.calls == 2 * len(pairs)
    again = MockPairJudge(); run(pack, out, config, again, mock=True); assert again.calls == 0
    always_a = analyze(pairs, read_csv(out))
    assert always_a['all']['chose_first_rate'] == 1 and always_a['all']['order_consistency'] == 0
    assert always_a['all']['accuracy']['estimate'] == pytest.approx(0.5)

    preferred = {frozenset((p['left'], p['right'])): p[p['human_pref']] for p in pairs}

    def pick(text, imgs):
        a, b = Path(imgs[0]).name.split('_')[0], Path(imgs[2]).name.split('_')[0]
        return 'A' if preferred[frozenset((a, b))] == a else 'B'
    oracle = MockPairJudge(pick)
    out2 = tmp_path / 'oracle.csv'; run(pack, out2, config, oracle, mock=True)
    summary = analyze(pairs, read_csv(out2))
    assert summary['clear_render_vs_render']['accuracy']['estimate'] == 1 and summary['clear_render_vs_render']['order_consistency'] == 1


def test_run_retries_failed(tmp_path):
    images, per = synthetic()
    pairs = build_pairs(images, per, mdc=1.0)[:2]
    pack = make_pack(tmp_path, pairs); config = load_json(HERE / 'judges.json'); out = tmp_path / 'r.csv'

    class Broken(MockPairJudge):
        def generate(self, text, images):
            self.calls += 1
            return '형식 오류'
    run(pack, out, config, Broken(), mock=True)
    assert all(r['status'] == 'failed' and '응답 앞부분' in r['error'] for r in read_csv(out))
    retry = MockPairJudge(); run(pack, out, config, retry, mock=True)
    assert retry.calls == 4


def test_decide():
    assert decide({'estimate': .9, 'ci95': [.75, .97]}, .85) == '대체 가능'
    assert decide({'estimate': .7, 'ci95': [.55, .85]}, .85) == '보조만'
    assert decide({'estimate': .55, 'ci95': [.4, .7]}, .85) == '쓰지 않음'
    assert decide({'estimate': None, 'ci95': None}, .85) == '판정 불가'
