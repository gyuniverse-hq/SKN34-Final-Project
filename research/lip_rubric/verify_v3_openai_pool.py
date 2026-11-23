"""Verify the completed image pairs and the blind-pool exclusion contract."""
import json
from collections import Counter
from pathlib import Path
from common import DATA, read_csv, sha256


def verify(out):
    rows=read_csv(out/'key.csv')
    excluded=set((out/'excluded_image_ids.txt').read_text(encoding='utf8').splitlines())
    ids=[r['image_id'] for r in rows]
    assert len(ids)==len(set(ids)), 'duplicate image_id'
    assert not set(ids)&excluded, 'excluded image_id reused'
    hashes=json.loads((out/'images_sha256.json').read_text(encoding='utf8'))
    expected={f'images/{i}_{s}.png' for i in ids for s in ('full','crop')}
    assert set(hashes)==expected, 'key/hash list mismatch'
    for name in expected:
        assert (out/name).is_file() and sha256(out/name)==hashes[name], f'file mismatch: {name}'
    actual={f'images/{p.name}' for p in (out/'images').glob('*.png')}
    assert actual==expected, 'orphan or missing image files'
    old_hashes=set()
    v3=DATA/'expansion_v3'
    for manifest in list(v3.glob('checklist_*/manifest.json'))+[v3/'ab_manifest.json']:
        if manifest.is_file():
            old_hashes.update(json.loads(manifest.read_text(encoding='utf8')).get('image_files_sha256',{}).values())
    summary={'images':len(ids),'source_images':len({r['lapa_stem'] for r in rows}),'face_ids':len({r['face_id'] for r in rows}),'excluded_id_intersection':len(set(ids)&excluded),'matching_v3_file_sha256':sum(h in old_hashes for h in hashes.values()),'variant_level':dict(sorted(Counter(f"{r['variant']}:{r['level'] or 'none'}" for r in rows).items()))}
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    return summary

if __name__=='__main__': verify(DATA/'expansion_v3_openai_pool')
