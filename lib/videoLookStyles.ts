import type { ApplicationProfileOverrides, MakeupZone, ZoneGeometry } from '@/types';

/**
 * Render-only finish of a video look, applied in the look AR only (lib/videoLookMakeup.ts): the painted colour, shape and
 * look-mode effects (soft-light blush, skin grade, glow). The product, its shade and the cart are never changed.
 * User decision (2026-11-13): in the video look AR, reproducing the video's finished face comes before the product-AR
 * principles (AR_SPEC 1-1 to 1-3, 6-5-3). Values are tuned by eye against the video's finished frame, not measured.
 */
export type VideoLookZoneStyle = {
  hex?: string;
  hexTo?: string;
  geometry?: ZoneGeometry;
  overrides?: ApplicationProfileOverrides;
};

export const VIDEO_LOOK_STYLES: Readonly<Record<string, Partial<Record<MakeupZone, VideoLookZoneStyle>>>> = {
  // 설윤 뿌까: pink-white even skin with a dewy nose and cheekbones, a high flush under the eyes, rose glossy lips,
  // a long dark wing and soft curled lashes (research/look6, finished frame e1gSkUdG6Bo_0002_final).
  e1gSkUdG6Bo: {
    // Real-device feedback (11-14): keep facial hair, shadows and skin texture, no patchy sampling near features. 11-14 balance:
    // the skin is evened by frequency separation (texture kept) instead of covered; blush and lip carry visible colour by colour
    // blend; the glow only lights raised points (local-contrast mask). The AR look strength slider scales all of it.
    foundation: { overrides: { coverageMultiplier: 0.45, skinEven: 0.6, skinWide: 0, skin: { tint: '#EFC9D2', tone: 0.25, clean: 0 } } },
    blush: {
      hex: '#E46F8C',
      geometry: { blushPlacement: 'apple', blushSize: 1.45, blushSoftness: 1 },
      overrides: { coverageMultiplier: 0.65, softLight: 2, blushColor: 1, skinAdapt: 0.6, skinWarmth: 0.28 },
    },
    highlighter: {
      hex: '#E3C6CA',
      geometry: { areas: ['nose_bridge', 'under_eye', 'chin'] },
      overrides: { coverageMultiplier: 0.8, glow: 0.6 },
    },
    contour: { hex: '#AE9598', overrides: { coverageMultiplier: 0.45 } },
    eyeshadow: {
      geometry: { innerPoint: { hex: '#FBE8ED', a1: 0.1, radius: 0.06 } },
      overrides: { coverageMultiplier: 0.6, underEyePearl: 0.3 },
    },
    eyeliner: { hex: '#3A2A26', geometry: { length: 0.3, thickness: 0.08, angle: 10 }, overrides: { coverageMultiplier: 0.85, linerTaper: 1 } },
    mascara: {
      geometry: { length: 0.95, lashCount: 14, lashSweep: 0.45, lashClump: 0.25, lashFan: 40, lashJitter: 0.8, lashWidth: 0.55 },
      overrides: { coverageMultiplier: 0.8, lashCurl: 1 },
    },
    brow: { overrides: { coverageMultiplier: 0.45 } },
    lip: {
      hex: '#B0606C',
      geometry: { centerHighlight: 0.2, overlip: 0.025, peakOverdraw: 0.018 },
      overrides: {
        coverageMultiplier: 0.85, lipColor: 0.45, lipGradient: 0.45, lipGloss: 2, skinAdapt: 0.8, skinWarmth: 0.28,
        material: { roughness: 0.03, specular: 1.9 },
      },
    },
  },
};

export function hasVideoLookStyle(videoId: string): boolean {
  return Object.prototype.hasOwnProperty.call(VIDEO_LOOK_STYLES, videoId);
}

export function videoLookStyle(videoId: string, zone: MakeupZone): VideoLookZoneStyle | undefined {
  const look = Object.prototype.hasOwnProperty.call(VIDEO_LOOK_STYLES, videoId) ? VIDEO_LOOK_STYLES[videoId] : undefined;
  return look && Object.prototype.hasOwnProperty.call(look, zone) ? look[zone] : undefined;
}
