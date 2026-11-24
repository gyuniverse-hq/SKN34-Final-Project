import json
import sys
from pathlib import Path

import pytest
from PIL import Image

HERE = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(HERE))
from common import checks, load_json, read_csv, write_csv
from rubric_examples import MockContentJudge, analyze, choose_examples, consensus, parse_question, prompt_parts, run

RUBRIC = load_json(HERE / 'rubric.json')
CIDS = [c['id'] for c in checks(RUBRIC)]


def answers(value, finish='satin'):
    return {cid: ('na' if finish == 'matte' and cid in ('q3_2', 'q3_3', 'q3_4') else value) for cid in CIDS}


def synthetic():
    images, votes = {}, {}
    for n in range(12):
        kind = 'sticker' if n in (0, 6) else 'real' if n in (5, 11) else 'render'
        split = 'pool' if n < 6 else 'test'
        i = f'i{n}'
        images[i] = {'image_id': i, 'face_id': f'f{n}', 'kind': kind, 'finish': 'satin', 'mouth': 'closed', 'split': split}
        level = 0 if kind == 'sticker' else 1 if kind == 'real' else (n % 3) / 2
        votes[i] = {f'R{r}': answers(int(level >= 0.5 or (level > 0 and r <= 2))) for r in range(1, 6)}
    return images, votes


def test_consensus_threshold():
    assert consensus([{'a': 1}] * 4 + [{'a': 0}], 'a') == ('yes', 4, 5)
    assert consensus([{'a': 1}] * 3 + [{'a': 0}] * 2, 'a')[0] is None
    assert consensus([{'a': 'na'}] * 5, 'a')[0] is None


def test_examples_pool_only_and_render_first():
    images, votes = synthetic()
    chosen, gallery = choose_examples(images, votes, RUBRIC)
    for cid, pick in chosen.items():
        for e in pick.values():
            assert images[e['image_id']]['split'] == 'pool'
        assert pick['yes']['kind'] == 'render' and pick['no']['kind'] == 'render'


def test_prompt_and_parse():
    images, votes = synthetic()
    chosen, _ = choose_examples(images, votes, RUBRIC)
    import random
    q = RUBRIC['questions'][2]
    parts = prompt_parts(q, chosen, {'image_id': 'x', 'finish': 'matte', 'mouth': 'open'}, random.Random(1))
    assert sum(k == 'image' for k, _ in parts) == 2 * len(q['checks']) + 2 and '"na"' in parts[-1][1]
    body = json.dumps({'checks': {'q3_1': 1, 'q3_2': 'na', 'q3_3': 'na', 'q3_4': 'na', 'q3_5': 0}, 'reason': '반사 없음'}, ensure_ascii=False)
    assert parse_question('```json\n' + body + '\n```', q, 'matte')['checks']['q3_5'] == 0
    with pytest.raises(ValueError):
        parse_question(body, q, 'glossy')


def make_pack(tmp, images, votes):
    chosen, _ = choose_examples(images, votes, RUBRIC)
    pack = tmp / 'pack'; (pack / 'examples').mkdir(parents=True); (pack / 'targets').mkdir()
    (pack / 'rubric.json').write_text(json.dumps(RUBRIC, ensure_ascii=False), encoding='utf8')
    (pack / 'rubric_examples.json').write_text(json.dumps({'examples': chosen}, ensure_ascii=False), encoding='utf8')
    targets = [{'image_id': i, 'finish': m['finish'], 'mouth': m['mouth']} for i, m in images.items() if m['split'] == 'test']
    write_csv(pack / 'targets.csv', targets)
    for e in {e['image_id'] for p in chosen.values() for e in p.values()}:
        Image.new('RGB', (4, 4)).save(pack / 'examples' / f'{e}_crop.png')
    for t in targets:
        for s in ('full', 'crop'):
            Image.new('RGB', (4, 4)).save(pack / 'targets' / f"{t['image_id']}_{s}.png")
    return pack, targets


def test_run_resume_and_analyze(tmp_path):
    images, votes = synthetic()
    pack, targets = make_pack(tmp_path, images, votes)
    config = load_json(HERE / 'judges.json'); out = tmp_path / 'r.csv'
    all_yes = MockContentJudge()
    run(pack, out, config, all_yes, mock=True)
    assert all_yes.calls == len(targets) * 5
    again = MockContentJudge(); run(pack, out, config, again, mock=True); assert again.calls == 0
    s = analyze(RUBRIC, images, votes, read_csv(out))
    assert s['images'] == len(targets) and s['vlm_full_score_rate'] == 1 and s['decision'] == '쓰지 않음'

    truth = {i: votes[i]['R5'] for i in images}

    class Oracle(MockContentJudge):
        def generate(self, parts, question):
            self.calls += 1
            target = next(v for k, v in reversed(parts) if k == 'image').split('/')[1].split('_')[0]
            return json.dumps({'checks': {c['id']: truth[target][c['id']] for c in question['checks']}, 'reason': '정답'}, ensure_ascii=False)
    out2 = tmp_path / 'o.csv'; run(pack, out2, config, Oracle(), mock=True)
    s2 = analyze(RUBRIC, images, votes, read_csv(out2))
    assert s2['mean_check_agreement'] == 1 > s['mean_check_agreement']
