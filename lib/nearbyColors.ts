import { ciede2000, hexToLabD65, hueDifference, labToLch, type Lab } from './colorDifference';
import type { MakeupZone, Product, Shade, Texture } from '@/types';

export const NEARBY_DIRECTIONS = ['similar', 'lighter', 'darker', 'muted', 'vivid'] as const;
export type NearbyDirection = typeof NEARBY_DIRECTIONS[number];
export interface ColorSwatch { product: Product; shade: Shade }
export interface IndexedSwatch extends ColorSwatch { lab: Lab; lch: ReturnType<typeof labToLch> }
export interface NearbyMatch extends ColorSwatch { deltaE: number }
export type NearbyGroups = Record<NearbyDirection, NearbyMatch[]>;

/** User-selected A policy (2026-11-12). Inclusive bounds; never relax an empty group. */
export const NEARBY_RULES = {
  similar: { maxDeltaE: 3, minL: -Infinity, maxL: Infinity, minC: -Infinity, maxC: Infinity, maxHue: Infinity },
  lighter: { maxDeltaE: 8, minL: 3, maxL: 8, minC: -5, maxC: 5, maxHue: 8 },
  darker: { maxDeltaE: 8, minL: -8, maxL: -3, minC: -5, maxC: 5, maxHue: 8 },
  muted: { maxDeltaE: 8, minL: -3, maxL: 3, minC: -12, maxC: -5, maxHue: 8 },
  vivid: { maxDeltaE: 8, minL: -3, maxL: 3, minC: 5, maxC: 12, maxHue: 8 },
} as const;

export const supportsNearby = (zone: MakeupZone | null) => zone === 'lip' || zone === 'blush';

/** Prepared once per catalog update, never from rendered camera pixels. */
export function indexNearbyColors(products: Product[]): IndexedSwatch[] {
  return products.flatMap((product) => {
    if (!supportsNearby(product.makeupZone) || !product.texture) return [];
    return product.shades.flatMap((shade) => {
      if (shade.measureMethod === 'placeholder' || shade.colorSource === 'placeholder') return [];
      const lab = hexToLabD65(shade.hex);
      return lab ? [{ product, shade, lab, lch: labToLch(lab) }] : [];
    });
  });
}

export function matchesNearbyRule(direction: NearbyDirection, deltaE: number, dL: number, dC: number, dh: number): boolean {
  const rule = NEARBY_RULES[direction];
  return [deltaE, dL, dC, dh].every(Number.isFinite) && deltaE <= rule.maxDeltaE && deltaE >= 0
    && dL >= rule.minL && dL <= rule.maxL && dC >= rule.minC && dC <= rule.maxC && Math.abs(dh) <= rule.maxHue;
}

const compareId = (a: string, b: string) => a < b ? -1 : a > b ? 1 : 0;

/** One best shade per product per direction; whole source product excluded.
 * Texture is an explicit filter only, never a penalty or a copied AR finish.
 */
export function findNearbyColors(index: IndexedSwatch[], anchor: IndexedSwatch | undefined, texture: Texture | null): NearbyGroups {
  const groups: NearbyGroups = { similar: [], lighter: [], darker: [], muted: [], vivid: [] };
  if (!anchor) return groups;
  const candidates = index.filter(({ product }) => product.makeupZone === anchor.product.makeupZone
    && product.id !== anchor.product.id && (!texture || product.texture === texture));
  for (const candidate of candidates) {
    const distance = ciede2000(anchor.lab, candidate.lab);
    const dL = candidate.lch.L - anchor.lch.L, dC = candidate.lch.C - anchor.lch.C;
    const dh = hueDifference(anchor.lch.h, candidate.lch.h);
    for (const direction of NEARBY_DIRECTIONS) {
      if (matchesNearbyRule(direction, distance, dL, dC, dh)) {
        groups[direction].push({ product: candidate.product, shade: candidate.shade, deltaE: distance });
      }
    }
  }
  for (const direction of NEARBY_DIRECTIONS) {
    const seen = new Set<string>();
    groups[direction].sort((a, b) => a.deltaE - b.deltaE
      || compareId(a.product.id, b.product.id) || compareId(a.shade.id, b.shade.id));
    groups[direction] = groups[direction].filter(({ product }) => {
      if (seen.has(product.id)) return false;
      seen.add(product.id);
      return true;
    });
  }
  return groups;
}
