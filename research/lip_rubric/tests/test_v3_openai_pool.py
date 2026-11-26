import csv
import json
import sys
from pathlib import Path
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from common import sha256
from verify_v3_openai_pool import verify


def test_pool_integrity_and_exclusion(tmp_path):
    (tmp_path/'images').mkdir()
    ident='a'*32
    files={}
    for suffix in ('full','crop'):
        p=tmp_path/'images'/f'{ident}_{suffix}.png'; p.write_bytes(b'test')
        files[f'images/{p.name}']=sha256(p)
    (tmp_path/'images_sha256.json').write_text(json.dumps(files))
    (tmp_path/'excluded_image_ids.txt').write_text('b'*32+'\n')
    with (tmp_path/'key.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['image_id','lapa_stem','face_id','variant','level']); w.writeheader(); w.writerow(dict(image_id=ident,lapa_stem='s',face_id='f',variant='current',level=''))
    assert verify(tmp_path)['excluded_id_intersection']==0
    (tmp_path/'excluded_image_ids.txt').write_text(ident+'\n')
    with pytest.raises(AssertionError,match='excluded'): verify(tmp_path)
