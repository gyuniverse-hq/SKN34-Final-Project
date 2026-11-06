import { ADJUST_DELTA_E } from '@/lib/colorGaps';
import { lookMatchType, LOOK_CORE_ZONES, missingCoreZones, similarLookShades } from '@/lib/lookProductMatch';
import type { Product } from '@/types';

const product = (id: string, zone: Product['makeupZone'], shadeId: string, hex: string, texture: Product['texture'] = 'matte'): Product => ({
  id, makeupZone: zone, shades: [{ id: shadeId, name: shadeId, hex }],
  brand: 'B', name: 'N', nameKo: 'N', category: 'lip', texture,
  priceKRW: 0, volume: '', description: '', keyIngredients: [], tags: [], imageUrl: '', searchKeyword: '',
});

test('exact needs a verified mapping with a real shade', () => {
  const p = product('p', 'lip', 's', '#AA2020');
  expect(lookMatchType({ mappingVerified: true, catalogProductId: 'p', catalogShadeId: 's' }, p, p.shades[0])).toBe('EXACT');
  expect(lookMatchType({ catalogProductId: 'p', catalogShadeId: 's' }, p, p.shades[0])).toBe('UNVERIFIED');
  expect(lookMatchType({ mappingVerified: true, catalogProductId: 'p' }, p)).toBe('SAME_PRODUCT_ALT_SHADE');
  expect(lookMatchType({}, p, p.shades[0])).toBe('MISSING');
});

test('similar shades stay in-zone, prefer the same finish, and never invent a hex', () => {
  const catalog = [
    product('a', 'lip', '1', '#AA2020', 'matte'),
    product('b', 'lip', '2', '#AB2121', 'glossy'),
    product('c', 'blush', '3', '#AA2020', 'matte'),
  ];
  const rows = similarLookShades('#AA2020', 'lip', catalog, 'matte', 3);
  expect(rows.every((row) => row.product.makeupZone === 'lip')).toBe(true);
  expect(rows[0]?.product.texture).toBe('matte');
  expect(rows[0]?.shade.hex).toBe('#AA2020');
  expect(rows.every((row) => row.deltaE <= ADJUST_DELTA_E)).toBe(true);
});

test('look try-on lists the seven core zones that are still empty', () => {
  expect(LOOK_CORE_ZONES).toEqual(['foundation', 'brow', 'eyeshadow', 'eyeliner', 'mascara', 'blush', 'lip']);
  expect(missingCoreZones(['lip', 'mascara', 'contour'])).toEqual(['foundation', 'brow', 'eyeshadow', 'eyeliner', 'blush']);
});
