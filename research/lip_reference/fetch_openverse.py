"""Collect lip finish reference photos from Openverse (CC-licensed, no API key).

Purpose: finish (gloss / sheen / texture) reference only — never color or a1 ground truth
(AR_SPEC 6-5-3, decision 2026-10-22). Images stay in research/data/ (git-ignored); the DB
keeps source, creator and license for every file.

  python research/lip_reference/fetch_openverse.py fetch            # search + download
  python research/lip_reference/fetch_openverse.py sheet            # contact sheets for review
  python research/lip_reference/fetch_openverse.py label <id8> <keep|reject> [finish] [note]
  python research/lip_reference/fetch_openverse.py summary
"""

import io
import json
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / 'research' / 'data' / 'reference' / 'openverse'
DB = ROOT / 'openverse.sqlite'
API = 'https://api.openverse.org/v1/images/'
UA = 'SKN34-lip-research/0.1 (student AR makeup project; finish reference only)'
MAX_BYTES = 8 * 1024 * 1024

# Finish → search terms (our MATERIALS names + metallic).
QUERIES = {
    'matte': ['matte lipstick', 'matte lips'],
    'velvet': ['velvet lipstick'],
    'cream': ['cream lipstick'],
    'satin': ['satin lipstick'],
    'sheer': ['lip tint', 'sheer lipstick'],
    'glossy': ['lip gloss', 'glossy lips'],
    'shimmer': ['shimmer lipstick', 'glitter lips'],
    'metallic': ['metallic lipstick'],
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS images (
  id TEXT PRIMARY KEY, query TEXT, query_finish TEXT, title TEXT, creator TEXT,
  license TEXT, license_version TEXT, source TEXT, landing_url TEXT, url TEXT,
  width INTEGER, height INTEGER, file TEXT,
  status TEXT DEFAULT 'new',      -- new | keep | reject
  finish TEXT,                    -- finish after visual review (may differ from query_finish)
  note TEXT, fetched_at TEXT
)"""


def db():
    ROOT.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.execute(SCHEMA)
    return con


def get(url, binary=False):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('too large')
    return data if binary else json.loads(data)


def fetch(pages=1):
    con = db()
    new = 0
    for finish, terms in QUERIES.items():
        for q in terms:
            for page in range(1, pages + 1):
                # No category filter: many lip photos are untagged; drawings are rejected at review.
                params = {'q': q, 'license_type': 'commercial', 'page_size': 20, 'page': page}
                res = None
                for attempt in range(3):
                    try:
                        res = get(API + '?' + urllib.parse.urlencode(params))
                        break
                    except Exception as e:  # timeout or rate limit: back off, keep what we have
                        print(f'  ! search "{q}" p{page} try {attempt + 1}: {e}')
                        time.sleep(5 * (attempt + 1))
                if res is None:
                    break
                time.sleep(1.5)
                for r in res.get('results', []):
                    if con.execute('SELECT 1 FROM images WHERE id=?', (r['id'],)).fetchone():
                        continue
                    folder = ROOT / 'images' / finish
                    folder.mkdir(parents=True, exist_ok=True)
                    file = folder / f"{r['id'][:8]}.jpg"
                    try:
                        from PIL import Image
                        raw = get(r['url'], binary=True)
                        img = Image.open(io.BytesIO(raw)).convert('RGB')
                        img.thumbnail((1600, 1600))
                        img.save(file, quality=92)
                    except Exception as e:
                        print(f'  ! download {r["id"][:8]}: {e}')
                        continue
                    con.execute(
                        'INSERT INTO images (id, query, query_finish, title, creator, license, license_version,'
                        ' source, landing_url, url, width, height, file, fetched_at)'
                        ' VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,datetime("now"))',
                        (r['id'], q, finish, r.get('title'), r.get('creator'), r.get('license'),
                         r.get('license_version'), r.get('source'), r.get('foreign_landing_url'), r.get('url'),
                         img.width, img.height, str(file.relative_to(ROOT))))
                    con.commit()
                    new += 1
                    time.sleep(0.2)
                print(f'{finish:9s} "{q}" p{page}: {len(res.get("results", []))} results')
    print('new images:', new)


def sheet():
    from PIL import Image, ImageDraw
    con = db()
    out = ROOT / 'sheets'
    out.mkdir(exist_ok=True)
    for finish in QUERIES:
        rows = con.execute("SELECT id, file FROM images WHERE query_finish=? AND status='new' ORDER BY id",
                           (finish,)).fetchall()
        for start in range(0, len(rows), 12):
            chunk = rows[start:start + 12]
            cell = 400
            grid = Image.new('RGB', (cell * 4, cell * 3), 'white')
            d = ImageDraw.Draw(grid)
            for k, (iid, file) in enumerate(chunk):
                im = Image.open(ROOT / file)
                im.thumbnail((cell, cell - 24))
                x, y = (k % 4) * cell, (k // 4) * cell
                grid.paste(im, (x, y + 24))
                d.rectangle([x, y, x + cell, y + 22], fill='black')
                d.text((x + 6, y + 5), f'{iid[:8]}', fill='yellow')
            name = out / f'{finish}_{start // 12 + 1}.jpg'
            grid.save(name, quality=85)
            print(name)


def label(id8, status, finish=None, note=None):
    con = db()
    n = con.execute('UPDATE images SET status=?, finish=COALESCE(?, finish, query_finish), note=? WHERE id LIKE ?',
                    (status, finish, note, id8 + '%')).rowcount
    con.commit()
    print('updated', n)


def summary():
    con = db()
    for row in con.execute('SELECT query_finish, status, COUNT(*) FROM images GROUP BY 1, 2 ORDER BY 1, 2'):
        print(*row)
    for row in con.execute("SELECT COALESCE(finish, query_finish), license, COUNT(*) FROM images"
                           " WHERE status='keep' GROUP BY 1, 2 ORDER BY 1"):
        print('keep', *row)


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'summary'
    if cmd == 'fetch':
        fetch(int(sys.argv[2]) if len(sys.argv) > 2 else 1)
    elif cmd == 'sheet':
        sheet()
    elif cmd == 'label':
        label(*sys.argv[2:6])
    else:
        summary()
