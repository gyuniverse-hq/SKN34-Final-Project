import type { ZoneGeometry } from '@/types';

/**
 * Mascara shape for look recipes. length/thickness are multipliers on the renderer default
 * (AR_SPEC 6-5-5). lower false skips lower lashes. Intensity is the zone strength, not hex.
 */
export const MASCARA_LOOKS = {
  slim: { length: 1.28, thickness: 0.78, lower: true, intensity: 0.72 },
  long_curl: { length: 1.48, thickness: 1.12, lower: true, intensity: 0.82 },
  volume_skinny: { length: 1.4, thickness: 1.3, lower: true, intensity: 0.8 },
  long: { length: 1.45, thickness: 1.28, lower: true, intensity: 0.85 },
  fine: { length: 1.12, thickness: 0.72, lower: false, intensity: 0.42 },
} as const;

export type MascaraLookId = keyof typeof MASCARA_LOOKS;

export function mascaraGeometry(style: MascaraLookId): ZoneGeometry {
  const look = MASCARA_LOOKS[style];
  return { length: look.length, thickness: look.thickness, lower: look.lower };
}
