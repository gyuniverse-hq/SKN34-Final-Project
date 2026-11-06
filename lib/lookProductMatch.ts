import { ADJUST_DELTA_E, recommendShades, type NearestShade } from '@/lib/colorGaps';
import type { MakeupZone, Product, Shade, Texture, VideoProductMapping } from '@/types';

/** Look try-on core layers. Contour and highlighter stay optional extras. */
export const LOOK_CORE_ZONES: MakeupZone[] = [
  'foundation', 'brow', 'eyeshadow', 'eyeliner', 'mascara', 'blush', 'lip',
];

export type LookMatchType = 'EXACT' | 'SAME_PRODUCT_ALT_SHADE' | 'SIMILAR' | 'UNVERIFIED' | 'MISSING';

export function lookMatchType(
  mapping: VideoProductMapping,
  product?: Product,
  shade?: Shade,
): LookMatchType {
  if (mapping.mappingVerified === true && product && shade) return 'EXACT';
  if (product && !shade) return 'SAME_PRODUCT_ALT_SHADE';
  if (mapping.catalogProductId && mapping.catalogShadeId && product && shade) return 'UNVERIFIED';
  return 'MISSING';
}

/** Same zone, optional same finish. Uses catalog hex only. Never invents a color. */
export function similarLookShades(
  hex: string,
  zone: MakeupZone,
  catalog: Product[],
  texture?: Texture | null,
  limit = 3,
): NearestShade[] {
  const ranked = recommendShades(hex, zone, catalog, null, 24);
  const close = ranked.filter((row) => row.deltaE <= ADJUST_DELTA_E);
  const sameFinish = texture ? close.filter((row) => row.product.texture === texture) : [];
  const rest = texture ? close.filter((row) => row.product.texture !== texture) : close;
  return (sameFinish.length ? [...sameFinish, ...rest] : close).slice(0, limit);
}

export function missingCoreZones(painted: MakeupZone[]): MakeupZone[] {
  const have = new Set(painted);
  return LOOK_CORE_ZONES.filter((zone) => !have.has(zone));
}
