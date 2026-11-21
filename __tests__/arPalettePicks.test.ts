import { pickPalette, type PaletteInputs } from '@/lib/arPalettePicks';
import type { ColorSwatch } from '@/lib/nearbyColors';

function swatch(id: string, hex: string, texture = 'matte'): ColorSwatch {
  return { product: { id, texture }, shade: { id: 's', hex } } as ColorSwatch;
}
const items = [swatch('few', '#DA636D'), swatch('many', '#F39373'),
  swatch('rose', '#802548', 'glossy'), swatch('brown', '#825843')];
const ratings = items.map(({ product }, i) => ({ productId: product.id,
  rating: [5, 4.9, 4.4, 4.5][i], reviews: [2, 200, 100, 100][i] }));

it('opens with review-adjusted picks and reserves an alternative family after repeated use', () => {
  const cold = pickPalette({ ratings, preferences: [] }, items, items);
  expect(cold.strategy).toBe('rating');
  expect(cold.items[0].product.id).toBe('many');
  expect(cold.items).toHaveLength(3);
  const liked = swatch('old', '#81264A', 'glossy');
  const preferences: PaletteInputs['preferences'] = [{ productId: 'old', shadeId: 's', weight: 18 }];
  const warm = pickPalette({ ratings, preferences }, [...items, liked], items);
  expect(warm.strategy).toBe('personalized');
  expect(warm.items[0].product.id).toBe('rose');
  expect(warm.items[2].product.id).not.toBe('rose');
});

it('uses only visible, usable shades and does not invent a rating for a missing product', () => {
  const unusable = { ...items[1], shade: { ...items[1].shade, colorSource: 'placeholder' as const } };
  const unknown = swatch('unrated', '#A32664');
  const visible = [unusable, unknown, items[0]];
  expect(pickPalette({ ratings, preferences: [] }, visible, visible).items).toEqual([items[0]]);
});
