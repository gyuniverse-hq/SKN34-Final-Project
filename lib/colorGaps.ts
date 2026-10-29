import { colorFamily, hexToLab, type ColorFamily } from './colorFamily';
import type { MakeupState, MakeupZone, Product, Shade, Texture } from '@/types';

/**
 * A look's color that no product of the look wears: find the nearest catalog shade, say how to
 * thicken or thin it, and otherwise build a shopping search. Colors are CIELAB distances (ΔE76).
 */

/** The look's own product shade is this close to the look color: nothing is missing. */
export const COVERED_DELTA_E = 8;
/** A catalog shade this close can be worn as is. */
export const CLOSE_DELTA_E = 8;
/** Farther than this, no amount of layering turns the shade into the look color. */
export const ADJUST_DELTA_E = 28;
/** The hue may differ by this much (degrees) for a shade to be deepened or lightened. */
export const ADJUST_HUE_DEG = 18;
/** Lightness gap (L*) below which there is nothing to thicken or thin. */
export const ADJUST_MIN_DL = 4;

export interface LookLine {
  product: Product;
  shade?: Shade;
}

export interface NearestShade {
  product: Product;
  shade: Shade;
  deltaE: number;
}

export type Amount = { dir: 'thicker'; layers: number } | { dir: 'thinner' } | null;

export type ColorGap =
  | { kind: 'nearest'; zone: MakeupZone; hex: string; nearest: NearestShade; amount: Amount }
  | { kind: 'search'; zone: MakeupZone; hex: string; query: string };

const lab = (hex: string) => hexToLab(hex);

export function deltaE(a: string, b: string): number {
  const x = lab(a), y = lab(b);
  return Math.hypot(x.L - y.L, x.a - y.a, x.b - y.b);
}

function hueDiff(a: string, b: string): number {
  const x = lab(a), y = lab(b);
  // Muted colors have no stable hue; treat them as the same hue.
  if (Math.hypot(x.a, x.b) < 12 || Math.hypot(y.a, y.b) < 12) return 0;
  const d = Math.abs(Math.atan2(x.b, x.a) - Math.atan2(y.b, y.a)) * (180 / Math.PI);
  return d > 180 ? 360 - d : d;
}

/** How to wear `shade` so it reads as `target`: thicker when the look color is deeper, thinner when lighter. */
export function amountToWear(target: string, shade: string): Amount {
  const dL = lab(shade).L - lab(target).L;
  if (Math.abs(dL) < ADJUST_MIN_DL) return null;
  return dL > 0 ? { dir: 'thicker', layers: dL < 10 ? 2 : 3 } : { dir: 'thinner' };
}

// Search keywords for Korean shopping sites (not UI text, so they stay Korean in every language).
const ZONE_QUERY: Record<MakeupZone, string> = {
  lip: '립',
  blush: '블러셔',
  eyeshadow: '아이섀도',
  eyeliner: '아이라이너',
  mascara: '마스카라',
  highlighter: '하이라이터',
  contour: '쉐딩',
  brow: '아이브로우',
  foundation: '파운데이션',
};
const FAMILY_QUERY: Record<ColorFamily, string> = {
  red: '레드',
  coral: '코랄',
  pink: '핑크',
  berry: '베리',
  nude: '누드',
  brown: '브라운',
};
const TEXTURE_QUERY: Record<Texture, string> = {
  matte: '매트',
  velvet: '벨벳',
  cream: '크림',
  satin: '새틴',
  sheer: '시어',
  glossy: '글로시',
  shimmer: '쉬머',
};

export function buildColorQuery(zone: MakeupZone, hex: string, texture: Texture): string {
  const { L, a, b } = lab(hex);
  const dark = L < 28 && Math.hypot(a, b) < 20;
  const family = dark ? '블랙' : FAMILY_QUERY[colorFamily(hex)];
  const skipTexture = zone === 'mascara' || zone === 'eyeliner' || zone === 'brow';
  return [family, ZONE_QUERY[zone], skipTexture ? '' : TEXTURE_QUERY[texture]].filter(Boolean).join(' ');
}

export function naverShoppingUrl(query: string): string {
  return `https://search.shopping.naver.com/search/all?query=${encodeURIComponent(query)}`;
}

/**
 * One gap per zone the look colors but no product line wears. `catalog` is every try-on product the
 * app can sell; the nearest shade of the same zone is taken from there.
 */
/** Same-zone shades nearest to `hex`, worn shade first, then by ΔE. */
export function recommendShades(
  hex: string,
  zone: MakeupZone,
  catalog: Product[],
  worn?: { productId: string; shadeId: string } | null,
  limit = 5
): NearestShade[] {
  const rows: NearestShade[] = [];
  for (const product of catalog) {
    if (product.makeupZone !== zone) continue;
    for (const shade of product.shades) {
      rows.push({ product, shade, deltaE: deltaE(hex, shade.hex) });
    }
  }
  rows.sort((a, b) => a.deltaE - b.deltaE);
  const wornRow = worn
    ? rows.find((r) => r.product.id === worn.productId && r.shade.id === worn.shadeId)
    : undefined;
  const rest = rows.filter((r) => r !== wornRow);
  return (wornRow ? [wornRow, ...rest] : rest).slice(0, limit);
}

export function findColorGaps(makeup: MakeupState, lines: LookLine[], catalog: Product[]): ColorGap[] {
  const gaps: ColorGap[] = [];
  for (const zone of Object.keys(ZONE_QUERY) as MakeupZone[]) {
    const setting = makeup[zone];
    if (!setting) continue;
    const covered = lines.some(
      (l) => l.product.makeupZone === zone && l.shade && deltaE(l.shade.hex, setting.hex) <= COVERED_DELTA_E
    );
    if (covered) continue;

    let best: NearestShade | null = null;
    for (const product of catalog) {
      if (product.makeupZone !== zone) continue;
      for (const shade of product.shades) {
        const d = deltaE(shade.hex, setting.hex);
        if (!best || d < best.deltaE) best = { product, shade, deltaE: d };
      }
    }
    if (best && best.deltaE <= CLOSE_DELTA_E) {
      gaps.push({ kind: 'nearest', zone, hex: setting.hex, nearest: best, amount: null });
    } else if (
      best &&
      best.deltaE <= ADJUST_DELTA_E &&
      hueDiff(best.shade.hex, setting.hex) <= ADJUST_HUE_DEG &&
      amountToWear(setting.hex, best.shade.hex)
    ) {
      gaps.push({ kind: 'nearest', zone, hex: setting.hex, nearest: best, amount: amountToWear(setting.hex, best.shade.hex) });
    } else {
      gaps.push({ kind: 'search', zone, hex: setting.hex, query: buildColorQuery(zone, setting.hex, setting.texture) });
    }
  }
  return gaps;
}
