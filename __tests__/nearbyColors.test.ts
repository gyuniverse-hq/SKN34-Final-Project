import { ciede2000, hexToLabD65, hueDifference, type Lab } from '@/lib/colorDifference';
import { findNearbyColors, indexNearbyColors, matchesNearbyRule, type NearbyDirection } from '@/lib/nearbyColors';
import type { Product } from '@/types';

const lab = ([L, a, b]: number[]): Lab => ({ L, a, b });
// Sharma, Wu, Dalal (2005), Table 1; same independent references as test_color.py.
it.each([
  [[50, 2.6772, -79.7751], [50, 0, -82.7485], 2.0425],
  [[50, 0, 0], [50, -1, 2], 2.3669],
  [[50, 2.5, 0], [73, 25, -18], 27.1492],
  [[60.2574, -34.0099, 36.2677], [60.4626, -34.1751, 39.4387], 1.2644],
  [[50, 2.5, 0], [50, 3.1736, 0.5854], 1],
] as [number[], number[], number][])('matches CIEDE2000 reference %j / %j', (a, b, expected) => {
  expect(ciede2000(lab(a), lab(b))).toBeCloseTo(expected, 4);
  expect(ciede2000(lab(b), lab(a))).toBeCloseTo(expected, 4);
  expect(ciede2000(lab(a), lab(a))).toBe(0);
});

it('converts sRGB D65 without the approximate family-filter matrix, rejecting malformed hex', () => {
  expect(hexToLabD65('#000000')).toEqual({ L: 0, a: 0, b: 0 });
  const white = hexToLabD65('#FFFFFF')!;
  expect(white.L).toBeCloseTo(100, 4);
  expect(white.a).toBeCloseTo(0, 4);
  expect(white.b).toBeCloseTo(0, 4);
  expect(hexToLabD65('#BE636A')!.L).toBeCloseTo(52.8555, 4);
  for (const hex of ['#xyzxyz', '#FFF', '', '#000000x', 'red']) expect(hexToLabD65(hex)).toBeNull();
});

it('uses the shortest circular hue distance at red and both signs at the wrap', () => {
  expect(hueDifference(357, 3)).toBe(6);
  expect(hueDifference(3, 357)).toBe(-6);
  expect(matchesNearbyRule('lighter', 4, 4, 0, hueDifference(357, 3))).toBe(true);
  expect(matchesNearbyRule('lighter', 4, 4, 0, hueDifference(350, 3))).toBe(false);
});

it.each([
  ['lighter', 3, 5, 8], ['lighter', 8, -5, -8],
  ['darker', -3, -5, -8], ['darker', -8, 5, 8],
  ['muted', -3, -12, 8], ['muted', 3, -5, -8],
  ['vivid', -3, 5, -8], ['vivid', 3, 12, 8],
] as [NearbyDirection, number, number, number][])('includes A boundaries for %s (%s, %s, %s)', (direction, dL, dC, dh) => {
  expect(matchesNearbyRule(direction, 8, dL, dC, dh)).toBe(true);
  expect(matchesNearbyRule(direction, 8.00001, dL, dC, dh)).toBe(false);
  expect(matchesNearbyRule(direction, 8, dL, dC, 8.00001)).toBe(false);
});

it('does not round near-boundary values or admit opposite/insufficient direction changes', () => {
  expect(matchesNearbyRule('similar', 3, 20, 20, 180)).toBe(true);
  expect(matchesNearbyRule('similar', 3.00001, 0, 0, 0)).toBe(false);
  expect(matchesNearbyRule('lighter', 4, 2.99999, 0, 0)).toBe(false);
  expect(matchesNearbyRule('lighter', 4, 8.00001, 0, 0)).toBe(false);
  expect(matchesNearbyRule('darker', 4, 3, 0, 0)).toBe(false);
  expect(matchesNearbyRule('muted', 4, 0, -4.99999, 0)).toBe(false);
  expect(matchesNearbyRule('vivid', 4, 3.00001, 5, 0)).toBe(false);
  expect(matchesNearbyRule('vivid', 4, 0, 12.00001, 0)).toBe(false);
});

function product(id: string, hexes: string[], overrides: Partial<Product> = {}): Product {
  return { id, brand: 'Test', name: id, nameKo: id, category: 'lip', makeupZone: 'lip', texture: 'matte',
    priceKRW: 0, volume: '', description: '', keyIngredients: [], tags: [], imageUrl: '', searchKeyword: '',
    shades: hexes.map((hex, i) => ({ id: String(i), name: String(i), hex })), ...overrides };
}

it('reproduces all five A directions from the reviewed Hince color example', () => {
  const index = indexNearbyColors([
    product('source', ['#BE636A', '#C2636B']), product('similar', ['#C2636B']),
    product('lighter', ['#CC6872']), product('darker', ['#B85864']),
    product('muted', ['#B96971']), product('vivid', ['#C55E69']),
  ]);
  const result = findNearbyColors(index, index[0], null);
  expect(result.similar[0].product.id).toBe('similar');
  expect(result.similar[0].deltaE).toBeCloseTo(0.82509, 4);
  for (const direction of ['lighter', 'darker', 'muted', 'vivid'] as const) {
    expect(result[direction].map((s) => s.product.id)).toContain(direction);
  }
  expect(Object.values(result).flat().some((s) => s.product.id === 'source')).toBe(false);
});

it('keeps finishes optional, zones separate, and only the best shade of each product in stable order', () => {
  const index = indexNearbyColors([
    product('source', ['#BE636A']),
    product('z', ['#C2636B', '#BE636A'], { texture: 'glossy' }),
    product('a', ['#BE636A']), product('blush', ['#BE636A'], { makeupZone: 'blush' }),
    product('eye', ['#BE636A'], { makeupZone: 'eyeshadow' }),
  ]);
  const all = findNearbyColors(index, index[0], null).similar;
  expect(all.map((s) => [s.product.id, s.shade.id])).toEqual([['a', '0'], ['z', '1']]);
  expect(findNearbyColors(index, index[0], 'matte').similar.map((s) => s.product.id)).toEqual(['a']);
  expect(findNearbyColors([...index].reverse(), index[0], null).similar).toEqual(all);
  expect(findNearbyColors(index, index.find((s) => s.product.id === 'blush'), null).similar).toEqual([]);
});

it('never widens empty groups and excludes placeholder/missing colors and unwearable products', () => {
  const index = indexNearbyColors([
    product('source', ['#BE636A']), product('far', ['#00FF00']),
    product('bad', ['garbage']), product('no-finish', ['#BE636A'], { texture: null }),
    product('placeholder', [], { shades: [{ id: 'p', name: 'p', hex: '#BE636A', measureMethod: 'placeholder' }] }),
    product('placeholder-source', [], { shades: [{ id: 'p', name: 'p', hex: '#BE636A', colorSource: 'placeholder' }] }),
  ]);
  expect(index.map((s) => s.product.id)).toEqual(['source', 'far']);
  expect(Object.values(findNearbyColors(index, index[0], null)).flat()).toEqual([]);
});
