import type { ZoneGeometry } from '@/types';

/** Lash shape fields a look can carry on top of length / thickness (see ZoneGeometry; all optional). */
type ShapeFields = Pick<ZoneGeometry, 'lashCount' | 'lashSweep' | 'lashClump' | 'lashFan' | 'lashJitter' | 'lowerLen' | 'lowerAlpha' | 'lowerCount' | 'lashWidth' | 'falseLashLen'>;
type MascaraLook = { length: number; thickness: number; lower: boolean; intensity: number } & ShapeFields;

/**
 * Mascara shape for look recipes. length/thickness are multipliers on the renderer default
 * (AR_SPEC 6-5-5). lower false skips lower lashes. Intensity is the zone strength, not hex.
 *
 * The first five are the product-type shapes of the video pipeline. The last six are read from the six demo look
 * videos' finished-look close-ups (research/lash_ref/looks.json, 11-09): lash length as a share of the eye width,
 * how dense, whether the strands bunch, whether the lower lashes show. length = measured / 0.145 / (0.75 + 0.5 * intensity).
 */
export const MASCARA_LOOKS = {
  slim: { length: 1.28, thickness: 0.78, lower: true, intensity: 0.72 },
  long_curl: { length: 1.48, thickness: 1.12, lower: true, intensity: 0.82 },
  volume_skinny: { length: 1.4, thickness: 1.3, lower: true, intensity: 0.8 },
  long: { length: 1.45, thickness: 1.28, lower: true, intensity: 0.85 },
  fine: { length: 1.12, thickness: 0.72, lower: false, intensity: 0.42 },
  /** 딸기 토끼상: few long strands between the spiky bunches; spiky lower lashes. */
  spiky_long: { length: 1.25, thickness: 0.6, lower: true, intensity: 0.8, lashCount: 10, lashClump: 0.3, lowerLen: 2.4, lowerAlpha: 4, lowerCount: 7, lashWidth: 1.8, falseLashLen: 1.3 },
  /** 연말 수상템: short, light and sparse; the lower lashes barely show. */
  short_light: { length: 1.15, thickness: 0.6, lower: true, intensity: 0.65, lashCount: 12, lashClump: 0.15, lowerLen: 1.6, lowerCount: 3, lashWidth: 1.2 },
  /** 청초 물복숭아: a thin fan of medium-length strands, small pointed bunches (eye photo, 11-11), very faint lower lashes. */
  fine_short: { length: 1.3, thickness: 0.9, lower: true, intensity: 0.7, lashCount: 16, lashClump: 0.3, lowerLen: 1.9, lowerAlpha: 1.5, lowerCount: 4, lashWidth: 1.4 },
  /** 카리나 멧갈라: medium strands with small pointed bunches (eye photo, 11-11), lower lashes clearly drawn. */
  thin_lower: { length: 1.45, thickness: 1, lower: true, intensity: 0.85, lashCount: 22, lashClump: 0.14, lowerLen: 3, lowerAlpha: 4, lowerCount: 8, lashWidth: 1.5 },
  /**
   * 설윤 뿌까: long, dense strands that fan out and curl up, with a few fine lower lashes at the outer corner (eye photo, 11-11).
   * Before 11-11 this was `comb` (14 straight parallel strands, no lower lashes, read from the video close-ups); the photo shows
   * a curled fan, so the straight comb is gone. 11-13: the 11-11 fan read as drawn comb teeth next to the finished frame
   * (too long, thick and spread), so it is shorter, finer and less spread.
   */
  long_fan: { length: 1.1, thickness: 0.7, lower: true, intensity: 0.55, lashCount: 14, lashSweep: 0.3, lashClump: 0.2, lashFan: 25, lashJitter: 0.3, lowerLen: 1.1, lowerAlpha: 1, lowerCount: 3, lashWidth: 0.8 },
  /** 윈터 또렷 청초: thin hair-like dense lashes, no bunches, faint lower lashes. */
  fine_dense: { length: 1.5, thickness: 1, lower: true, intensity: 0.85, lashCount: 24, lashClump: 0.3, lashJitter: 0.8, lowerLen: 1.9, lowerAlpha: 1.5, lowerCount: 4, lashWidth: 1.4 },
} satisfies Record<string, MascaraLook>;

export type MascaraLookId = keyof typeof MASCARA_LOOKS;

export function mascaraGeometry(style: MascaraLookId): ZoneGeometry {
  const { intensity: _intensity, ...shape }: MascaraLook = MASCARA_LOOKS[style];
  return shape;
}
