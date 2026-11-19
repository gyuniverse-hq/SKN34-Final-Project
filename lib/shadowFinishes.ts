import type { ShadowFinish, ShadowParticle, ZoneSetting } from '@/types';

/** Finishes with Voronoi pearl grains (11-17 v6; v7: metallic is a glitter variant chosen by the product). */
export const PEARL_FINISH_IDS: ShadowFinish[] = ['shimmer', 'glitter'];

/** Lid-only finish chips (not catalog Texture). 11-17 v7: one glitter chip; a metallic product makes it a metallic glitter. */
export const SHADOW_FINISH_IDS: ShadowFinish[] = ['matte', 'satin', 'shimmer', 'glitter', 'glossy'];

/** Numbers are the try-on table; keep in sync with SHADOW_FINISHES in faceTrackerHtml.ts. 'metallic' stays for older saved states. */
export const SHADOW_FINISHES: Record<
  ShadowFinish,
  { opacity: number; roughness: number; sparkleDensity: number; specular: number }
> = {
  matte: { opacity: 0.7, roughness: 1, sparkleDensity: 0, specular: 0 },
  shimmer: { opacity: 0.3, roughness: 0.4, sparkleDensity: 0.35, specular: 0.4 },
  glitter: { opacity: 0.3, roughness: 0.2, sparkleDensity: 0.75, specular: 0.95 },
  glossy: { opacity: 0.25, roughness: 0.05, sparkleDensity: 0, specular: 0.9 },
  satin: { opacity: 0.55, roughness: 0.55, sparkleDensity: 0, specular: 0.45 },
  metallic: { opacity: 0.6, roughness: 0.3, sparkleDensity: 0.2, specular: 1 },
};

export function shadowFinishOf(setting: ZoneSetting | null | undefined): ShadowFinish {
  if (!setting) return 'matte';
  const named = setting.geometry?.shadowFinish;
  // 11-17 v7: the metallic chip is gone; a state saved with it reads as glitter.
  if (named === 'metallic') return 'glitter';
  if (named && Object.prototype.hasOwnProperty.call(SHADOW_FINISHES, named)) return named;
  if (setting.geometry?.sparkle != null && setting.geometry.sparkle <= 0) return 'matte';
  if (setting.texture === 'shimmer') return 'shimmer';
  if (setting.texture === 'glossy') return 'glossy';
  return 'matte';
}

/**
 * Glitter particle traits read from the product and shade names (the catalog has no material field), so an estimate
 * like the colour-chip estimate: metal (metallic glitter), large (sequin-size flakes), holo (strong iridescence).
 */
export function glitterTraitsOf(productName: string, shadeName = ''): ShadowParticle {
  const text = `${productName} ${shadeName}`;
  return {
    metal: /메탈|metal|포일|foil|크롬|chrome/i.test(text),
    large: /스팽|spangle|sequin|파츠|청크|chunky|플레이크|flake/i.test(text),
    holo: /홀로|holo|프리즘|prism|오로라|aurora/i.test(text),
  };
}
