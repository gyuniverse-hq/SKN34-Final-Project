#!/usr/bin/env python3
"""Read-only integrity checks. External originals are required; see README_FIRST.md."""
import argparse
import collections
import hashlib
import json
from pathlib import Path

D = Path(__file__).resolve().parent
ORIGINAL_SHA256 = {
    'resolved_inputs_359_원본v13.jsonl': '9223ad217cc1f8cfe6274479256cb4c3473be858d05da0512b7f0d6353e0113a',
    'fixtures_world_v1.3.json': '3dce47c2419032f7bd0b6f500b9a02f301609725dbab9de6a9ea636c01d4a803',
    '누적검수_359_원본보존.jsonl': 'a517e742a285054166000407f8fa607285a54ccd226af2dd1bc44373f7ba0490',
}

def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]

def validate(originals_dir=D, *, reviews=None):
    paths = {name: Path(originals_dir) / name for name in ORIGINAL_SHA256}
    if reviews is not None:
        paths['누적검수_359_원본보존.jsonl'] = Path(reviews)
    for name, path in paths.items():
        if not path.is_file():
            raise FileNotFoundError(f'External original required: {path}; see README_FIRST.md')
        assert hashlib.sha256(path.read_bytes()).hexdigest() == ORIGINAL_SHA256[name], f'Original hash mismatch: {name}'
    original = read_jsonl(paths['resolved_inputs_359_원본v13.jsonl'])
    patched = read_jsonl(D / 'resolved_inputs_359_fixture_patch.jsonl')
    cum = read_jsonl(paths['누적검수_359_원본보존.jsonl'])
    changes = json.loads((D / 'fixture_patch_audit.json').read_text(encoding='utf-8'))
    world_original = json.loads(paths['fixtures_world_v1.3.json'].read_text(encoding='utf-8'))
    world = json.loads((D / 'fixtures_world_patched.json').read_text(encoding='utf-8'))
    # Inspect the patch separately; never edit or substitute the original world.
    restored = json.loads(json.dumps(world))
    restored['arStates'].pop('A_UNDO_READY')
    for key in ('patchIsSynthetic', 'patchedFor', 'productionGoldApproved'):
        restored['meta'].pop(key)
    assert restored == world_original, 'Unexpected changes beyond the documented world patch'
    inputs = read_jsonl(D / '1A_mock_contract_cases_11.jsonl')
    assert len(original) == len(patched) == len(cum) == 359
    assert [x['case_id'] for x in original] == [x['case_id'] for x in patched] == [x['case_id'] for x in cum]
    assert len({x['case_id'] for x in cum}) == 359
    assert collections.Counter(x['review_status'] for x in cum) == {'APPROVAL_CANDIDATE':25, 'NEEDS_POLICY':10, 'NOT_REVIEWED':324}
    assert all(not x['approved_gold_assertions'] for x in cum)
    changed = []
    for a, b in zip(original, patched):
        if a == b:
            continue
        assert {k:v for k,v in a.items() if k!='test_input'} == {k:v for k,v in b.items() if k!='test_input'}
        assert {k:v for k,v in a['test_input'].items() if k!='context'} == {k:v for k,v in b['test_input'].items() if k!='context'}
        changed.append(b['case_id'])
    assert len(changed) == 8 and set(changed) == {x['case_id'] for x in changes}
    product_shades = {x['id']:set(x['shades']) for x in world['products']}
    invalid = []
    for x in patched:
        c = x['test_input']['context']; p, s = c.get('selectedProductId'), c.get('selectedShadeId')
        if p and s and s not in product_shades.get(p,set()):
            invalid.append(x['case_id'])
    assert set(invalid) == {'E-I-05-E', 'E-XC08'}
    assert world['arStates']['A_UNDO_READY']['stateVersion'] == 4
    assert world['arStates']['A_UNDO_READY']['layers']['lip']['intensity'] == 0.5
    assert world['meta']['productionGoldApproved'] is False
    assert len(inputs) == 11 and len({x['id'] for x in inputs}) == 11
    manifest = json.loads((D.parent / 'MANIFEST_SHA256.json').read_text(encoding='utf-8'))
    for name, entry in manifest.items():
        data = (D.parent / name).read_bytes()
        assert len(data) == entry['bytes'] and hashlib.sha256(data).hexdigest() == entry['sha256'], f'Manifest mismatch: {name}'
    return {'validated':True, 'original_cases':len(original), 'unchanged_review_records':len(cum),
        'context_patched':len(changed), 'context_patch_ids':changed, 'expected_negative_fk':invalid,
        'unexpected_fk_errors':0, '1a_mock_candidates':len(inputs),
        'review_states':dict(collections.Counter(x['review_status'] for x in cum)),
        'gold_approved':0, 'real_llm_test_count':0, 'real_ar_test_count':0,
        'source_cumulative_sha256':ORIGINAL_SHA256['누적검수_359_원본보존.jsonl']}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--originals-dir', type=Path, default=D)
    parser.add_argument('--reviews', type=Path, help='Alternative filename for the unchanged review original')
    args = parser.parse_args()
    try:
        print(json.dumps(validate(args.originals_dir, reviews=args.reviews), ensure_ascii=False, indent=2))
    except (FileNotFoundError, AssertionError, KeyError, ValueError) as exc:
        parser.exit(2, f'Validation failed: {exc}\n')

if __name__ == '__main__':
    main()
