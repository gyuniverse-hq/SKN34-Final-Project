import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image
from typer.testing import CliRunner

from vlm_judge.__main__ import app
from vlm_judge.images import discover, import_existing, jpeg, lip_box
from vlm_judge.judge_adapter import JudgeResult, OpenAIJudge
from vlm_judge.pipeline import PROJECT, make_plan, normalized, run
from vlm_judge.report import human_compare, majority, ordinal, wilson
from vlm_judge.schemas import Color


def config():
    return json.loads((PROJECT / 'judges.json').read_text(encoding='utf-8')) | {'model': 'fake'}


def sample(data: Path, name='one', bare=True):
    folder = data / 'sets' / name
    folder.mkdir(parents=True)
    for i, role in enumerate(('bare', 'real', 'ar') if bare else ('real', 'ar')):
        Image.new('RGB', (120+i*10, 200), (50+i*40, 30, 80)).save(folder / f'{role}.png')
    return folder


class Fake:
    def __init__(self):
        self.calls = 0

    async def judge(self, prompt, images, schema):
        self.calls += 1
        values = {
            'Color': {'color_band': '2-4', 'reason': 'Similar.'},
            'Placement': {'overflow': 'none', 'missing': 'none', 'edge': 'natural_soft', 'corner_fade': 'natural', 'placement_score': 4, 'reason': 'Close.'},
            'Texture': {'contrast_closer': 'X', 'highlight_closer': 'tie', 'texture_closer': 'Y', 'x_finish_look': 'satin', 'y_finish_look': 'matte', 'x_plastic_look': False, 'y_plastic_look': True, 'reason': 'Different.'},
            'NaturalSingle': {'guess': 'real_makeup', 'confidence': 3, 'naturalness': 4, 'awkward_regions': ['none'], 'awkward_reasons': ['none'], 'reason': 'Natural.'},
            'NaturalPair': {'choice': 'X', 'reason': 'First.'},
        }
        return JudgeResult(values[schema.__name__], 100, 20)


def test_full_run_cache_and_report(tmp_path):
    sample(tmp_path)
    sample(tmp_path, 'no-bare', bare=False)
    sets, errors = discover(tmp_path)
    assert not errors
    fake = Fake()
    all_metrics = {'color', 'placement', 'texture', 'naturalness'}
    first = asyncio.run(run(tmp_path, sets, config(), fake, all_metrics, 42))
    assert fake.calls == 45  # 27 for complete set, 18 for no-bare
    summary = json.loads((first / 'summary.json').read_text(encoding='utf-8'))
    assert summary['valid'] == 45
    assert summary['excluded_no_bare'] == ['no-bare']
    assert summary['texture']['contrast_closer'] == {'wins': 0, 'total': 1, 'pass': False}
    assert 'VLM 추정' in (first / 'report.md').read_text(encoding='utf-8')
    assert 'data:image/jpeg;base64,' in (first / 'report.html').read_text(encoding='utf-8')
    before = fake.calls
    second = asyncio.run(run(tmp_path, sets, config(), fake, all_metrics, 42))
    assert first != second and fake.calls == before
    assert json.loads((second / 'summary.json').read_text(encoding='utf-8'))['input_tokens'] == 0


def test_discovery_fallback_and_cli(tmp_path):
    sample(tmp_path, bare=False)
    (tmp_path / 'sets' / 'broken').mkdir()
    sets, errors = discover(tmp_path)
    assert len(sets) == 1 and len(errors) == 1 and sets[0].bare is None
    box, method = lip_box(Image.new('RGB', (80, 100)))
    assert box == (0.25, 0.5, 0.75, 1.0) and method == 'fallback'
    assert jpeg(Image.new('RGB', (3000, 1500)))[:2] == b'\xff\xd8'
    runner = CliRunner()
    assert runner.invoke(app, ['validate', '--data', str(tmp_path)]).exit_code == 1
    assert runner.invoke(app, ['plan', '--data', str(tmp_path)]).exit_code == 1
    (tmp_path / 'sets' / 'broken').rmdir()
    assert runner.invoke(app, ['validate', '--data', str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ['plan', '--data', str(tmp_path)]).exit_code == 0


def test_import_only_explicit_sets(tmp_path):
    folder = sample(tmp_path / 'source')
    assert import_existing(folder, tmp_path / 'dest') == 1
    assert (folder / 'real.png').exists()
    with pytest.raises(FileExistsError):
        import_existing(folder, tmp_path / 'dest')


def test_statistics_order_and_blinding(tmp_path):
    assert majority(['ar', 'bare']) == 'tie'
    assert ordinal(['<=2', '6-10', '2-4'], ['<=2', '2-4', '6-10']) == '2-4'
    assert wilson(0, 0) is None
    low, high = wilson(5, 10)
    assert low == pytest.approx(.2366, abs=.001) and high == pytest.approx(.7634, abs=.001)
    v = {'contrast_closer': 'X', 'highlight_closer': 'Y', 'texture_closer': 'tie', 'x_finish_look': 'matte', 'y_finish_look': 'gloss', 'x_plastic_look': False, 'y_plastic_look': True}
    assert normalized('texture', ['real', 'bare', 'ar'], v)['contrast_closer'] == 'bare'
    assert normalized('texture', ['real', 'ar', 'bare'], v)['contrast_closer'] == 'ar'
    assert normalized('natural_pair', ['ar', 'real'], {'choice': 'Y'})['choice'] == 'real'
    sample(tmp_path)
    sets, _ = discover(tmp_path)
    assert make_plan(sets, config(), {'texture', 'naturalness'}, 42) == make_plan(sets, config(), {'texture', 'naturalness'}, 42)


def test_no_external_permission(monkeypatch):
    monkeypatch.delenv('ALLOW_EXTERNAL_JUDGE', raising=False)
    monkeypatch.setenv('OPENAI_API_KEY', 'do-not-print')
    with pytest.raises(RuntimeError, match='ALLOW_EXTERNAL_JUDGE=true'):
        OpenAIJudge(config())


def test_openai_request_uses_blind_labels_and_structured_output(monkeypatch):
    monkeypatch.setenv('ALLOW_EXTERNAL_JUDGE', 'true')
    monkeypatch.setenv('OPENAI_API_KEY', 'fake-local-test-key')
    judge = OpenAIJudge(config())
    judge._client.responses.parse = AsyncMock(return_value=SimpleNamespace(
        output_parsed=Color(color_band='2-4', reason='Similar.'),
        usage=SimpleNamespace(input_tokens=123, output_tokens=45)))
    result = asyncio.run(judge.judge('prompt', [('Reference', b'first'), ('Candidate X', b'second')], Color))
    assert result.value['color_band'] == '2-4'
    assert (result.input_tokens, result.output_tokens) == (123, 45)
    params = judge._client.responses.parse.await_args.kwargs
    assert params['store'] is False and params['text_format'] is Color
    assert 'temperature' not in params
    content = params['input'][0]['content']
    assert [part['type'] for part in content] == ['input_text', 'input_text', 'input_image', 'input_text', 'input_image']
    assert [content[1]['text'], content[3]['text']] == ['Reference', 'Candidate X']
    assert content[2]['image_url'] == 'data:image/jpeg;base64,Zmlyc3Q='
    assert content[4]['image_url'] == 'data:image/jpeg;base64,c2Vjb25k'


def test_openai_missing_structured_response_is_not_success(monkeypatch):
    monkeypatch.setenv('ALLOW_EXTERNAL_JUDGE', 'true')
    monkeypatch.setenv('OPENAI_API_KEY', 'fake-local-test-key')
    judge = OpenAIJudge(config())
    judge._client.responses.parse = AsyncMock(return_value=SimpleNamespace(output_parsed=None, usage=None))
    with pytest.raises(ValueError, match='no structured response'):
        asyncio.run(judge.judge('prompt', [('Candidate', b'image')], Color))


def test_openai_model_list_check(monkeypatch):
    monkeypatch.setenv('ALLOW_EXTERNAL_JUDGE', 'true')
    monkeypatch.setenv('OPENAI_API_KEY', 'fake-local-test-key')
    judge = OpenAIJudge(config())

    async def listed_models():
        yield SimpleNamespace(id='fake')
        yield SimpleNamespace(id='another')

    judge._client.models.list = listed_models
    asyncio.run(judge.verify_model())
    judge._config = config() | {'model': 'missing'}
    with pytest.raises(ValueError, match='another, fake'):
        asyncio.run(judge.verify_model())


def test_human_spearman(tmp_path):
    path = tmp_path / 'responses.csv'
    path.write_text('image_id,rater,guess_real,score,regions,reasons\na/real,1,true,1,,edge\nb/real,1,true,2,,edge\nc/real,1,true,3,,color\n', encoding='utf-8')
    singles = {f'{k}/real': {'naturalness': n, 'guess': 'real_makeup'} for k, n in [('a', 1), ('b', 2), ('c', 3)]}
    result = human_compare(path, singles, config())
    assert result['spearman'] == pytest.approx(1) and result['guess_agreement'] == 1
    assert result['level'] == '대체 가능'


def test_invalid_response_retries_and_no_cache(tmp_path):
    sample(tmp_path, bare=False)
    sets, _ = discover(tmp_path)

    class Invalid(Fake):
        async def judge(self, prompt, images, schema):
            self.calls += 1
            return JudgeResult({'color_band': 'invalid', 'reason': 'bad'}, 3, 2)

    fake = Invalid()
    settings = config() | {'repeats': 1}
    output = asyncio.run(run(tmp_path, sets, settings, fake, {'color'}, 42, no_cache=True))
    calls = [json.loads(line) for line in (output / 'raw' / 'calls.jsonl').read_text(encoding='utf-8').splitlines()]
    assert fake.calls == 3
    assert calls[0]['status'] == 'invalid' and len(calls[0]['attempts']) == 3
    assert not list((tmp_path / 'runs' / '.cache').glob('*.json'))


def test_no_cache_bypasses_previous_result(tmp_path):
    sample(tmp_path, bare=False)
    sets, _ = discover(tmp_path)
    fake = Fake()
    settings = config() | {'repeats': 1}
    asyncio.run(run(tmp_path, sets, settings, fake, {'color'}, 42))
    assert fake.calls == 1
    asyncio.run(run(tmp_path, sets, settings, fake, {'color'}, 42, no_cache=True))
    assert fake.calls == 2
