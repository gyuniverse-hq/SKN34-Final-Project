"""Import the Olive Young makeup color sheet into the app catalog (AR_SPEC 6-15).

Usage:
    python scripts/data/import_oliveyoung.py <oliveyoung_makeup_colors_*.xlsx>

Writes lib/devCatalog/oliveyoung.ts (generated, do not edit by hand). Standard library only.

Rules:
- Colors are estimates from product-page color chips / swatches: measureMethod 'estimated',
  colorSource 'option_chip' | 'color_compare' | 'product_photo', with Lab and confidence kept.
  Measured values (6-15 CSV) always take precedence later.
- Option image URLs and review wording are NOT imported (not needed for color use).
- Prices are not in the sheet: priceKRW 0 + tag 'price-unchecked' (never invented).
- Options without a color (palettes, package photos, no image) are skipped and reported.
- Duplicate options of the same shade (set / refill bundles) are merged into one shade.
"""
import json
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter, OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'lib' / 'devCatalog' / 'oliveyoung.ts'
NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'

# 소분류 → (category, makeupZone). None zone = listed in the shop but not painted by AR.
CATEGORY = {
    '립틴트': ('lip', 'lip'),
    '립글로스': ('lip', 'lip'),
    '립케어': ('lip', 'lip'),
    '립스틱': ('lip', 'lip'),
    '립라이너': ('lip', None),      # liner draws the edge only; full-lip paint would mislead
    '블러셔': ('cheek', 'blush'),
    '아이섀도우': ('eye', 'eyeshadow'),
    '아이브로우': ('eye', None),
    '아이라이너': ('eye', None),
    '마스카라': ('eye', None),
    '쿠션': ('base', None),
    'BB/CC': ('base', None),
    '파우더/팩트': ('base', None),
    '프라이머/베이스': ('base', None),
    '파운데이션': ('base', None),
}
TEXTURES = {'matte', 'velvet', 'glossy', 'satin', 'sheer', 'cream', 'shimmer'}


def read_xlsx(path):
    z = zipfile.ZipFile(path)
    shared = []
    if 'xl/sharedStrings.xml' in z.namelist():
        root = ET.fromstring(z.read('xl/sharedStrings.xml'))
        shared = [''.join(t.text or '' for t in si.iter(NS + 't')) for si in root.findall(NS + 'si')]
    sheet = sorted(n for n in z.namelist() if n.startswith('xl/worksheets/sheet'))[0]
    root = ET.fromstring(z.read(sheet))

    def col(ref):
        n = 0
        for ch in ''.join(c for c in ref if c.isalpha()):
            n = n * 26 + ord(ch) - 64
        return n - 1

    rows = []
    for r in root.find(NS + 'sheetData').findall(NS + 'row'):
        vals = {}
        for c in r.findall(NS + 'c'):
            v = c.find(NS + 'v')
            if v is None:
                inline = c.find(NS + 'is')
                val = ''.join(x.text or '' for x in inline.iter(NS + 't')) if inline is not None else None
            else:
                val = shared[int(v.text)] if c.get('t') == 's' else v.text
            vals[col(c.get('r'))] = val
        rows.append([vals.get(i) for i in range(max(vals) + 1)] if vals else [])
    header = rows[0]
    return [dict(zip(header, r + [None] * (len(header) - len(r)))) for r in rows[1:]]


def clean_name(name):
    name = re.sub(r'\[[^\]]*\]', ' ', name or '')
    return re.sub(r'\s+', ' ', name).strip()


def color_source(text):
    t = text or ''
    if t.startswith('제품 사진') or '제품 사진' in t and '컬러칩' not in t:
        return 'product_photo'
    if '색상비교' in t:
        return 'color_compare'
    return 'option_chip'


def texture_source(reason):
    r = reason or ''
    if r.startswith('상품명'):
        return 'name_keyword'
    if r.startswith('리뷰 수분감'):
        return 'review_survey'
    if r.startswith('리뷰'):
        return 'review_summary'
    return 'default'


def confidence(text):
    m = re.match(r'\s*([0-9.]+)', text or '')
    return round(float(m.group(1)), 2) if m else None


def shade_id(code, used, index):
    base = re.sub(r'[^a-z0-9]+', '-', (code or '').lower()).strip('-') or f'o{index}'
    sid, k = base, 2
    while sid in used:
        sid, k = f'{base}-{k}', k + 1
    used.add(sid)
    return sid


def main():
    if len(sys.argv) < 2:
        sys.exit('usage: python scripts/data/import_oliveyoung.py <xlsx>')
    rows = read_xlsx(sys.argv[1])
    groups = OrderedDict()
    for r in rows:
        groups.setdefault(r['상품번호'], []).append(r)

    products, skipped, unknown_types = [], Counter(), Counter()
    for goods_no, rs in groups.items():
        first = rs[0]
        sub = first['제품유형(소분류)']
        if sub not in CATEGORY:
            unknown_types[sub] += len(rs)
            continue
        category, zone = CATEGORY[sub]
        checked = (first['수집일시'] or '')[:10]

        shades, used, seen = [], set(), set()
        for i, r in enumerate(rs):
            hexv = (r['올리브영 HEX'] or '').strip().upper()
            if not re.fullmatch(r'#[0-9A-F]{6}', hexv):
                skipped[(r['색 출처'] or '색 없음').split(' – ')[0][:40]] += 1
                continue
            code = (r['호수'] or '').strip()
            label = (r['호수이름'] or '').strip()
            key = code or label or clean_name(r['올리브영 옵션명'])
            if key in seen:
                skipped['같은 호수 중복 옵션'] += 1
                continue
            seen.add(key)
            name = ' '.join(x for x in [code, label] if x) or clean_name(r['올리브영 옵션명'])
            shade = {
                'id': shade_id(code or label, used, i),
                'name': name,
                'hex': hexv,
                'measureMethod': 'estimated',
                'colorSource': color_source(r['색 출처']),
                'colorCheckedAt': checked,
            }
            if r['L*'] not in (None, ''):
                shade['labEstimated'] = {'L': float(r['L*']), 'a': float(r['a*']), 'b': float(r['b*'])}
            conf = confidence(r['색 신뢰도'])
            if conf is not None:
                shade['colorConfidence'] = conf
            shades.append(shade)

        tex_counts = Counter(r['제형'] for r in rs if r['제형'] in TEXTURES)
        texture = tex_counts.most_common(1)[0][0] if tex_counts else 'satin'
        reason = next((r['판정 근거'] for r in rs if r['제형'] == texture), None) if tex_counts else None
        name = clean_name(first['상품명'])
        products.append({
            'id': f'oy-{goods_no.lower()}',
            'brand': first['브랜드명'],
            'name': name,
            'nameKo': name,
            'category': category,
            'makeupZone': zone if shades else None,
            'texture': texture,
            'textureSource': texture_source(reason),
            'priceKRW': 0,
            'volume': '',
            'shades': shades,
            'description': '',
            'keyIngredients': [],
            'tags': ['oliveyoung', 'price-unchecked', sub],
            'imageUrl': '',
            'searchKeyword': f"{first['브랜드명']} {name}",
            'sourceUrl': f'https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo={goods_no}',
            'checkedAt': checked,
        })

    body = json.dumps(products, ensure_ascii=False, indent=2)
    OUT.write_text(
        '// Generated by scripts/data/import_oliveyoung.py from the Olive Young color sheet. Do not edit.\n'
        '// Colors are estimates (measureMethod "estimated"); prices are unchecked (priceKRW 0).\n'
        "import type { Product } from '@/types';\n\n"
        f'export const OLIVEYOUNG_PRODUCTS: Product[] = {body};\n',
        encoding='utf-8',
    )
    tryon = [p for p in products if p['makeupZone']]
    print(f'products: {len(products)} (AR try-on: {len(tryon)}), shades: {sum(len(p["shades"]) for p in products)}')
    print('try-on shades by zone:', dict(Counter(p['makeupZone'] for p in tryon for _ in p['shades'])))
    print('skipped options:', dict(skipped))
    if unknown_types:
        print('unknown product types (not imported):', dict(unknown_types))


if __name__ == '__main__':
    main()
