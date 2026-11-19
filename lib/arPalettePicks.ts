import { colorFamily, type ColorFamily } from './colorFamily';
import { hexToLabD65, labToLch } from './colorDifference';
import type { ColorSwatch } from './nearbyColors';

export interface PaletteInputs {
  ratings: { productId: string; rating: number; reviews: number }[];
  preferences: { productId: string; shadeId: string; weight: number }[];
}
export type PickStrategy = 'rating' | 'personalized';
export const AR_PALETTE_LOOP_THRESHOLD = 7;
const key = (product: string, shade: string) => JSON.stringify([product, shade]);
export const paletteSwatchKey = ({ product, shade }: ColorSwatch) => key(product.id, shade.id);

export function placePicksAround(
  items: readonly ColorSwatch[], picks: readonly ColorSwatch[], anchor: ColorSwatch,
) {
  const suggested = new Set(picks);
  const ordinary = items.filter(item => item === anchor || !suggested.has(item));
  const anchorIndex = ordinary.indexOf(anchor);
  const left = anchorIndex < 0 ? [] : ordinary.slice(0, anchorIndex);
  const right = ordinary.slice(anchorIndex + 1);
  const neighbors = picks.filter(item => item !== anchor);
  const center = [...neighbors.slice(1, 2), anchor, ...neighbors.slice(0, 1), ...neighbors.slice(2)];
  // A looping palette can start at this group while keeping the rest of the ring in order.
  return left.length + center.length + right.length > AR_PALETTE_LOOP_THRESHOLD
    ? [...center, ...right, ...left]
    : [...left, ...center, ...right];
}

function features(item: ColorSwatch) {
  if (!item.product.texture || item.shade.measureMethod === 'placeholder' || item.shade.colorSource === 'placeholder') return null;
  const lab = hexToLabD65(item.shade.hex);
  if (!lab) return null;
  const { L, C } = labToLch(lab);
  return { family: colorFamily(item.shade.hex), L, C, texture: item.product.texture };
}

/** The rating belongs to the product. Use shade features for preference and variety. */
export function pickPalette(inputs: PaletteInputs, catalog: readonly ColorSwatch[], visible: readonly ColorSwatch[]) {
  const byId = new Map(catalog.map(item => [key(item.product.id, item.shade.id), item]));
  const preferences = inputs.preferences.flatMap(({ productId, shadeId, weight }) => {
    const item = byId.get(key(productId, shadeId));
    const f = item && features(item);
    return f && weight > 0 ? [{ ...f, weight }] : [];
  });
  const evidence = preferences.reduce((sum, p) => sum + p.weight, 0);
  const personalShare = 0.75 * evidence / (evidence + 12);
  const strategy: PickStrategy = evidence ? 'personalized' : 'rating';
  const eligible = inputs.ratings.filter(r => r.reviews > 0 && r.rating >= 1 && r.rating <= 5);
  if (!eligible.length) return { strategy, items: [] as ColorSwatch[] };
  const prior = eligible.reduce((sum, r) => sum + r.rating, 0) / eligible.length;
  const quality = new Map(eligible.map(r => [r.productId, (r.reviews * r.rating + 30 * prior) / (r.reviews + 30)]));
  const ranked = visible.flatMap((item, position) => {
    const stars = quality.get(item.product.id);
    const f = stars === undefined ? null : features(item);
    if (!f || stars === undefined) return [];
    let affinity = 0;
    for (const p of preferences) {
      const similarity = 0.4 * Number(f.family === p.family) + 0.2 * Number(f.texture === p.texture)
        + 0.2 * Math.max(0, 1 - Math.abs(f.L - p.L) / 35) + 0.2 * Math.max(0, 1 - Math.abs(f.C - p.C) / 50);
      affinity += p.weight * similarity;
    }
    const score = (1 - personalShare) * (stars - 1) / 4 + personalShare * affinity / (evidence || 1);
    return [{ item, family: f.family, score, position }];
  }).sort((a, b) => b.score - a.score || a.position - b.position);

  const items: ColorSwatch[] = [];
  const products = new Set<string>();
  const families = new Set<ColorFamily>();
  while (items.length < 3) {
    const candidates = ranked.filter(r => !products.has(r.item.product.id));
    const diversify = !evidence || items.length === 2;
    const next = (diversify && candidates.find(r => !families.has(r.family))) || candidates[0];
    if (!next) break;
    items.push(next.item);
    products.add(next.item.product.id);
    families.add(next.family);
  }
  return { strategy, items };
}
