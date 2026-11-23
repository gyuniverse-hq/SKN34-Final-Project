"""Add the original v2 examples to generated expansion packs, then rebuild their ZIPs."""
import json
import shutil
import zipfile
from pathlib import Path

from common import DATA, sha256


def restore(output):
    source = DATA / 'pack/rating_pack'
    guide = json.loads((source / 'guide.json').read_text(encoding='utf8'))
    packs = sorted(output.glob('pack_*'))
    if not packs:
        raise ValueError('추가 평가 묶음이 없습니다')
    for pack in packs:
        rating = pack / 'rating_pack'
        images = rating / 'images'
        for example in guide.values():
            for side in ('pass', 'fail'):
                name = example.get(side, {}).get('image')
                if not name:
                    continue
                file = (source / name).resolve()
                if file.parent != (source / 'images').resolve():
                    raise ValueError('가이드 이미지 경로 오류')
                shutil.copyfile(file, images / file.name)
        shutil.copyfile(source / 'guide.json', rating / 'guide.json')
        current_rubric = json.loads((rating / 'rubric.json').read_text(encoding='utf8'))
        if current_rubric != json.loads((source / 'rubric.json').read_text(encoding='utf8')):
            raise ValueError('기존 v2 채점표와 새 채점표가 다릅니다')
        shutil.copyfile(source / 'rubric.json', rating / 'rubric.json')
        page_path = rating / 'index.html'
        page = page_path.read_text(encoding='utf8')
        old_name = "a.download=code+'_ratings.csv'"
        new_name = "a.download=code+'_'+packHash.slice(0,8)+'_ratings.csv'"
        if page.count(old_name) == 1:
            page_path.write_text(page.replace(old_name, new_name), encoding='utf8')
        elif page.count(new_name) != 1:
            raise ValueError('평가 CSV 파일명 코드를 확인하세요')
        manifest_path = pack / 'manifest.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf8'))
        manifest['guide_sha256'] = sha256(rating / 'guide.json')
        manifest['rubric_sha256'] = sha256(rating / 'rubric.json')
        manifest['guide_note'] = 'Same v2 pilot examples; they can influence scoring and are not new ratings.'
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf8')
        target = output / f'rating_{pack.name}.zip'
        with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
            for file in rating.rglob('*'):
                if file.is_file():
                    archive.write(file, Path('rating_pack') / file.relative_to(rating))
        print(target, flush=True)


if __name__ == '__main__':
    restore(DATA / 'expansion_20261114')
