import type { ShadowFinish, ZoneSetting } from '@/types';

/** Lid-only finishes (not catalog Texture). Numbers are the try-on table. */
export const SHADOW_FINISH_IDS: ShadowFinish[] = ['matte', 'shimmer', 'glitter', 'glossy'];

export const SHADOW_FINISHES: Record<
  ShadowFinish,
  { opacity: number; roughness: number; sparkleDensity: number; specular: number }
> = {
  matte: { opacity: 0.7, roughness: 1, sparkleDensity: 0, specular: 0 },
  shimmer: { opacity: 0.3, roughness: 0.4, sparkleDensity: 0.35, specular: 0.4 },
  glitter: { opacity: 0.3, roughness: 0.2, sparkleDensity: 0.75, specular: 0.95 },
  glossy: { opacity: 0.25, roughness: 0.05, sparkleDensity: 0, specular: 0.9 },
};

export function shadowFinishOf(setting: ZoneSetting | null | undefined): ShadowFinish {
  if (!setting) return 'matte';
  const named = setting.geometry?.shadowFinish;
  if (named === 'matte' || named === 'shimmer' || named === 'glitter' || named === 'glossy') return named;
  if (setting.geometry?.sparkle != null && setting.geometry.sparkle <= 0) return 'matte';
  if (setting.texture === 'shimmer') return 'shimmer';
  if (setting.texture === 'glossy') return 'glossy';
  return 'matte';
}
