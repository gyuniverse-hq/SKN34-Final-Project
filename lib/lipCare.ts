import { hexToLab } from '@/lib/colorFamily';
import type { Product, Shade, Texture, ZoneCare } from '@/types';

/**
 * Lip tab layout (11-10, user): colour lips under four finish chips, and one "립케어" chip holding lip oils and lip balms. A care
 * product is a separate layer drawn over the colour lip (or the bare lip): shine and texture on top, almost no colour.
 *
 * Decided by the product NAME, not the catalog tag: the "립케어" tag also covers tinted serums, cheek-and-lip pots and matte bars.
 */
const OIL_NAME = /오일|\boil\b/i;
const BALM_NAME = /밤|balm/i;
/** Lip skincare (essence, serum, ampoule, sleeping mask...): not a colour and not an oil / balm, so not in the AR lip list. */
const BASE_CARE_NAME = /에센스|essence|세럼|serum|세린|앰플|ampoule|슬리핑|sleeping|마스크|mask|트리트먼트|treatment|스크럽|scrub/i;
/** A tinted serum or colour essence is still a colour lip. */
const TINTED_NAME = /틴티드|틴트|컬러|tinted|tint|colou?r/i;

type Named = Pick<Product, 'name' | 'nameKo'>;
const nameOf = (product: Named) => `${product.nameKo || ''} ${product.name || ''}`;

export function lipCareKind(product: Named): ZoneCare['kind'] | null {
  const name = nameOf(product);
  if (OIL_NAME.test(name)) return 'oil';
  if (BALM_NAME.test(name)) return 'balm';
  return null;
}

/** Lip skincare that the AR lip tab leaves out (user: no base products in the lip tab). */
export function isLipBaseCare(product: Named): boolean {
  const name = nameOf(product);
  return BASE_CARE_NAME.test(name) && lipCareKind(product) === null && !TINTED_NAME.test(name);
}

export type LipTextureChip = 'matte' | 'cream' | 'glossy' | 'shimmer';
export const LIP_TEXTURE_CHIPS: LipTextureChip[] = ['matte', 'cream', 'glossy', 'shimmer'];

/** The lip tab's four finish chips: velvet sits with matte, satin with cream, sheer with glossy. */
export function lipTextureChip(texture: Texture | null | undefined): LipTextureChip | null {
  switch (texture) {
    case 'matte':
    case 'velvet':
      return 'matte';
    case 'cream':
    case 'satin':
      return 'cream';
    case 'glossy':
    case 'sheer':
      return 'glossy';
    case 'shimmer':
      return 'shimmer';
    default:
      return null;
  }
}

function clamp01(v: number): number {
  return Math.max(0, Math.min(1, v));
}

/**
 * How much of a care product's colour chip may show on a bare lip, 0..1. 0 = clear product: the chip is a packaging colour
 * (blue, pale blue, yellow, white, grey) or a placeholder, so the lip keeps its own colour and only gains the shine.
 * A lip-like chip (pink / red / coral / brown, hue 320°..65°) scales with its chroma, and a doubtful extraction scales it down.
 */
export function lipCareTint(shade: Pick<Shade, 'hex' | 'colorSource' | 'colorConfidence'>): number {
  if (shade.colorSource === 'placeholder') return 0;
  const { a, b } = hexToLab(shade.hex);
  const chroma = Math.hypot(a, b);
  if (chroma < 12) return 0;
  const hue = ((Math.atan2(b, a) * 180) / Math.PI + 360) % 360;
  if (hue < 320 && hue > 65) return 0;
  let tint = clamp01((chroma - 12) / 33);
  if (shade.colorConfidence != null && shade.colorConfidence < 0.7) tint *= clamp01(shade.colorConfidence / 0.7);
  return Math.round(tint * 100) / 100;
}

/** The `care` field of the lip care layer for this product and chip, or undefined for any other lip product. */
export function lipCareFor(product: Named, shade: Pick<Shade, 'hex' | 'colorSource' | 'colorConfidence'>): ZoneCare | undefined {
  const kind = lipCareKind(product);
  return kind ? { kind, tint: lipCareTint(shade) } : undefined;
}

/** Care layer strength: fixed for now (the intensity slider stays with the colour lip). */
export const LIP_CARE_INTENSITY = 0.65;
