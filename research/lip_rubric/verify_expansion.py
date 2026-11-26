"""Check generated hashes, independent splits, ZIP contents and the offline rating flow."""
import csv
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

from playwright.sync_api import sync_playwright

from common import DATA, read_csv, sha256
from db import connect, import_pack
from expansion_scores import run as summarize_scores
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lip_texture'))
from render import CHROME


def verify(output):
    packs = sorted(output.glob('pack_*'))
    if not packs:
        raise ValueError('평가 묶음이 없습니다')
    previous = {row['face_id'] for row in read_csv(DATA / 'pack/key.csv')}
    old_manifest = json.loads((DATA / 'pack/manifest.json').read_text(encoding='utf8'))
    previous.update(row['face_id'] for row in old_manifest['practice_sources'])
    face_splits, ids = {}, set()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=CHROME, headless=True)
        try:
            for index, pack in enumerate(packs):
                rating = pack / 'rating_pack'
                manifest = json.loads((pack / 'manifest.json').read_text(encoding='utf8'))
                data = json.loads((rating / 'pack.json').read_text(encoding='utf8'))
                key = read_csv(pack / 'key.csv')
                by_id = {item['random_id']: item for item in key}
                assert sha256(rating / 'pack.json') == manifest['pack_sha256']
                assert sha256(rating / 'rubric.json') == manifest['rubric_sha256']
                assert len(key) == len(data['items']) and len(data['practice']) == 3
                for item in key:
                    assert item['random_id'] not in ids
                    ids.add(item['random_id'])
                    assert item['face_id'] not in previous, '기존 본 평가 또는 연습 얼굴과 겹칩니다'
                    prior = face_splits.setdefault(item['face_id'], item['split'])
                    assert prior == item['split'], '같은 얼굴이 pool과 test에 동시에 존재합니다'
                    for suffix in ('full', 'crop'):
                        name = f"rating_pack/images/{item['random_id']}_{suffix}.png"
                        assert sha256(pack / name) == manifest['image_files_sha256'][name]
                        if item['repeat_of']:
                            assert item['repeat_of'] in by_id
                            original = rating / 'images' / f"{item['repeat_of']}_{suffix}.png"
                            assert sha256(pack / name) == sha256(original), '반복 사진이 원본과 다릅니다'
                archive_path = output / f'rating_{pack.name}.zip'
                with zipfile.ZipFile(archive_path) as archive:
                    assert archive.testzip() is None
                    assert not any(name.endswith(('key.csv', 'manifest.json')) for name in archive.namelist())
                context = browser.new_context(accept_downloads=True)
                page = context.new_page()
                page.goto((rating / 'index.html').resolve().as_uri())
                page.locator('#rater').fill('R999')
                page.locator('#folder').set_input_files(str(rating.resolve()))
                page.locator('#begin').click()
                page.locator('#app:not([hidden])').wait_for(timeout=30000)
                assert '연습' in page.locator('#progressLabel').inner_text()
                if index == 0:
                    for _ in range(4):
                        page.evaluate("""() => {
                          for (let i=0;i<25;i++) document.querySelectorAll('.line')[i].querySelector('button').click();
                          document.querySelector('#overall button').click();
                        }""")
                        if _ < 3:
                            page.locator('#next').click()
                    assert '본 채점' in page.locator('#progressLabel').inner_text()
                    with page.expect_download() as result:
                        page.locator('#export').click()
                    assert result.value.suggested_filename == f"R999_{manifest['pack_sha256'][:8]}_ratings.csv"
                    with tempfile.TemporaryDirectory() as directory:
                        file = Path(directory) / 'ratings.csv'
                        result.value.save_as(str(file))
                        with file.open(encoding='utf-8-sig', newline='') as stream:
                            rows = list(csv.DictReader(stream))
                        assert len(rows) == 1 and rows[0]['pack_hash'] == manifest['pack_sha256']
                context.close()
                print(f'{pack.name}: {len(key)}개, 브라우저 열기 통과', flush=True)
        finally:
            browser.close()
    with tempfile.TemporaryDirectory() as directory:
        test_db = Path(directory) / 'test.db'
        shutil.copyfile(DATA / 'eval.db', test_db)
        con = connect(test_db)
        try:
            previous_count = con.execute('select count(*) from images').fetchone()[0]
            for pack in packs:
                import_pack(con, pack)
            assert con.execute('select count(*) from images').fetchone()[0] == previous_count + len(ids)
        finally:
            con.close()
        with tempfile.TemporaryDirectory(dir=DATA) as summary_directory:
            summary_path = Path(summary_directory) / 'scores'
            summarize_scores(test_db, output, summary_path, 5)
            summary = json.loads((summary_path / 'summary.json').read_text(encoding='utf8'))
            assert summary['scored_images'] == 0 and summary['unscored_images'] == len(ids) - 4 * len(packs)
    print('기존 DB의 임시 복사본에 모든 묶음 등록 통과', flush=True)


if __name__ == '__main__':
    verify(DATA / 'expansion_20261114')
