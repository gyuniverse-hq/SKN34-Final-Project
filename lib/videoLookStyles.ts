import type { ApplicationProfileOverrides, MakeupZone, ZoneGeometry } from '@/types';

/**
 * Render-only finish of a video look, applied in the look AR only (lib/videoLookMakeup.ts): the painted colour, shape and
 * look-mode effects (soft-light blush, skin grade, glow). The product, its shade and the cart are never changed.
 * User decision (2026-11-13): in the video look AR, reproducing the video's finished face comes before the product-AR
 * principles (AR_SPEC 1-1 to 1-3, 6-5-3). Values are tuned against the video's finished frame (by eye, and where a
 * bare photo of the same face exists, by zone ΔE against the finished photo).
 */
export type VideoLookZoneStyle = {
  hex?: string;
  hexTo?: string;
  geometry?: ZoneGeometry;
  overrides?: ApplicationProfileOverrides;
};

export const VIDEO_LOOK_STYLES: Readonly<Record<string, Partial<Record<MakeupZone, VideoLookZoneStyle>>>> = {
  // 카리나 멧갈라: pale even skin, cool-pink apple blush, short upturned dark wing, doll lashes with a soft outer
  // lower line, champagne lid → brown outer V, ash-straight brows, milky-pink glass lips (user bare/final pair
  // 2026-11-17, research/data/look6/n5otfjJSSQc/pair). No lenses / face warp. Product hex and cart stay untouched.
  n5otfjJSSQc: {
    // pair fit r4 (2026-11-17, quality first): face ΔE 9.39→7.17, skin texture 1.38→1.20 (final 1.06). The wide clean
    // carries the even skin; the blush is wide and soft rather than a round patch; liner and lashes stay light because the
    // final lash line is brighter than the bare one; the lip is a cool rosy gloss with little warm skin pull. No lenses.
    foundation: {
      overrides: {
        coverageMultiplier: 0.4,
        skinEven: 1,
        skinWide: 0.45,
        lightAdapt: 0.7,
        toneMap: 0.55,
        skin: { tint: '#EED0C6', tone: 0.22, clean: 0.4 },
      },
    },
    blush: {
      hex: '#E06890',
      geometry: { blushPlacement: 'apple', blushSize: 1.4, blushSoftness: 1 },
      overrides: { coverageMultiplier: 1.05, softLight: 3.3, blushColor: 1.1, skinAdapt: 0.45, skinWarmth: 0.05, lightAdapt: 0.7 },
    },
    highlighter: {
      hex: '#F0E0D4',
      geometry: { areas: ['nose_bridge', 'under_eye', 'chin', 'philtrum'] },
      overrides: { coverageMultiplier: 0.85 },
    },
    contour: { hex: '#C4A090', overrides: { coverageMultiplier: 0.35 } },
    eyeshadow: {
      hex: '#F5D8D6',
      hexTo: '#A2837A',
      geometry: { innerPoint: { hex: '#FBECEA', a1: 0.14, radius: 0.055 } },
      overrides: { coverageMultiplier: 0.32, underEyePearl: 0.3 },
    },
    eyeliner: {
      hex: '#3A2E2A',
      geometry: { length: 0.14, thickness: 0.05, angle: 8, linerSoftness: 0.45, linerLower: false },
      overrides: { coverageMultiplier: 0.25, linerTaper: 1 },
    },
    mascara: {
      hex: '#2A201C',
      geometry: {
        length: 1.5, lashCount: 20, lashSweep: 0.22, lashClump: 0.12, lashFan: 42, lashJitter: 0.85, lashWidth: 0.45,
        lowerCount: 8, lowerLen: 1.8, lowerAlpha: 2.0,
      },
      overrides: { coverageMultiplier: 0.35, lashCurl: 1 },
    },
    brow: { hex: '#8B7358', overrides: { coverageMultiplier: 0.75 } },
    lip: {
      // Expo Go 11-17: a light pigment layer lifted the lip above the wearer's own (grey-lilac, floating). The hue goes on by
      // colour blend and the pigment stays thin: lip ΔL +9.0 -> +4.4 against a +2.0 target.
      hex: '#B87884',
      geometry: { centerHighlight: 0.08, overlip: 0.03, peakOverdraw: 0.02 },
      overrides: {
        coverageMultiplier: 0.35, lipColor: 1, lipGradient: 0.5, lipGloss: 1, skinAdapt: 0.25, skinWarmth: 0, lightAdapt: 0.7,
        material: { roughness: 0.04, specular: 2.0 },
      },
    },
  },
  // 딸기 토끼상: warm even skin, a wide rose flush on the cheeks, a soft brown-pink lid, sparse brown lash clumps and a
  // blurred coral-red velvet lip (bare/final pair fit 2026-11-17, research/data/look6/ZAozXs-ZZik/pair s8: face ΔE 10.71→8.06;
  // the catalog look covered the face white, drew spiky false lashes and a lavender lip). No lenses.
  'ZAozXs-ZZik': {
    foundation: {
      overrides: { coverageMultiplier: 0.25, skinEven: 1, skinWide: 0.45, skin: { tint: '#F2C8BE', tone: 0.15, clean: 0.4 } },
    },
    blush: {
      hex: '#E2687A',
      geometry: { blushPlacement: 'apple', blushSize: 1.5, blushSoftness: 1 },
      overrides: { coverageMultiplier: 1.25, softLight: 3.3, blushColor: 1.3, skinAdapt: 0.3, skinWarmth: 0 },
    },
    highlighter: { hex: '#F2DCD0', geometry: { areas: ['nose_bridge', 'chin'] }, overrides: { coverageMultiplier: 0.6 } },
    // The olive catalog contour read grey-green on this pink skin.
    contour: { hex: '#B48C80', overrides: { coverageMultiplier: 0.15 } },
    eyeshadow: { hex: '#E3A09A', hexTo: '#94605A', overrides: { coverageMultiplier: 0.6, underEyePearl: 0 } },
    eyeliner: {
      hex: '#4A3028',
      geometry: { linerSoftness: 0.7 },
      overrides: { coverageMultiplier: 0.25, linerTaper: 0.6 },
    },
    mascara: {
      hex: '#3A2620',
      geometry: {
        falseLash: [], length: 1.35, lashCount: 16, lashSweep: 0.15, lashClump: 0.35, lashFan: 40, lashJitter: 1, lashWidth: 0.5,
        lowerCount: 7, lowerLen: 1.8, lowerAlpha: 2,
      },
      overrides: { coverageMultiplier: 0.45, lashCurl: 1 },
    },
    brow: { hex: '#7C5C4C', overrides: { coverageMultiplier: 0.4 } },
    lip: {
      hex: '#D2504E',
      geometry: { centerHighlight: 0.08 },
      overrides: {
        coverageMultiplier: 0.55, lipColor: 0.7, lipGradient: 1, lipGloss: 0.8, skinAdapt: 0.2, skinWarmth: 0,
        material: { roughness: 0.2, specular: 0.8 },
      },
    },
  },
  // 연말 수상템: cool porcelain skin, a cool-pink flush high under the eyes, a pink pearl lid, separated lash clumps and a
  // sheer rose gloss lip (bare/final pair fit 2026-11-17, research/data/look6/4QR0tre9yBI/pair y3b; the catalog look had a peach
  // blush, a flat coral lip and a black wing). The lip hue is pulled from the hex at full chroma, so the hex itself is muted.
  // The bangs cover the brows, so the brow tint stays low (it tinted the bang strands). No lenses.
  '4QR0tre9yBI': {
    foundation: {
      overrides: { coverageMultiplier: 0.35, skinEven: 1, skinWide: 0.45, skin: { tint: '#F4D6DA', tone: 0.25, clean: 0.45 } },
    },
    blush: {
      hex: '#EC8A9E',
      geometry: { blushPlacement: 'under_eye', blushSize: 1.3, blushSoftness: 1 },
      overrides: { coverageMultiplier: 1, softLight: 2.6, blushColor: 1, skinAdapt: 0.3, skinWarmth: 0 },
    },
    highlighter: {
      hex: '#F6ECEC',
      geometry: { areas: ['nose_bridge', 'chin', 'under_eye'] },
      overrides: { coverageMultiplier: 0.7 },
    },
    contour: { hex: '#C9A6A0', overrides: { coverageMultiplier: 0.2 } },
    eyeshadow: {
      hex: '#F0B8BC',
      hexTo: '#C07880',
      geometry: { innerPoint: { hex: '#FBEFF0', a1: 0.16, radius: 0.06 } },
      overrides: { coverageMultiplier: 0.6, underEyePearl: 0.35 },
    },
    eyeliner: {
      hex: '#5A3A36',
      geometry: { linerStyle: 'classic_winged', length: 0.05, thickness: 0.04, linerSoftness: 0.6 },
      overrides: { coverageMultiplier: 0.3, linerTaper: 0.8 },
    },
    mascara: {
      hex: '#2A201C',
      geometry: {
        length: 1.45, lashCount: 18, lashSweep: 0.15, lashClump: 0.4, lashFan: 40, lashJitter: 0.9, lashWidth: 0.55,
        lowerCount: 8, lowerLen: 2, lowerAlpha: 2.4,
      },
      overrides: { coverageMultiplier: 0.55, lashCurl: 1 },
    },
    brow: { hex: '#6E5850', overrides: { coverageMultiplier: 0.2 } },
    lip: {
      hex: '#B85A6C',
      geometry: { centerHighlight: 0.3 },
      overrides: {
        coverageMultiplier: 0.45, lipColor: 0.4, lipGradient: 1, lipGloss: 2.8, skinAdapt: 0.1, skinWarmth: 0,
        material: { roughness: 0.04, specular: 2.0 },
      },
    },
  },
  // 윈터 또렷 청초: cool porcelain skin, a wide cool-pink apple flush, a peach-pink lid with under-eye pearl (no glitter),
  // a thin dark-brown wing, fine dense curled lashes, light-brown brows and a rose gloss gradient lip (user bare/final pair
  // 2026-11-17, research/data/look6/fDqBPI1SaWY/pair w4b: face ΔE 8.97→5.96, bare→final itself 4.94). The catalog look was a
  // yellow-bright foundation, peach matte lip and grey shimmer shadow with glitter. No lenses / face warp.
  fDqBPI1SaWY: {
    foundation: {
      overrides: { coverageMultiplier: 0.25, skinEven: 1, skinWide: 0.45, skin: { tint: '#F0D0D6', tone: 0.18, clean: 0.45 } },
    },
    blush: {
      hex: '#E87090',
      geometry: { blushPlacement: 'apple', blushSize: 1.45, blushSoftness: 1 },
      overrides: { coverageMultiplier: 1.2, softLight: 3.4, blushColor: 1.4, skinAdapt: 0.3, skinWarmth: 0 },
    },
    highlighter: {
      hex: '#F4E8E6',
      geometry: { areas: ['nose_bridge', 'chin', 'under_eye', 'philtrum'] },
      overrides: { coverageMultiplier: 0.95 },
    },
    contour: { hex: '#A89898', overrides: { coverageMultiplier: 0.15 } },
    eyeshadow: {
      hex: '#E8A8B0',
      hexTo: '#B87880',
      geometry: { innerPoint: { hex: '#FBECEC', a1: 0.14, radius: 0.05 }, glitter: false, sparkle: 0 },
      overrides: { coverageMultiplier: 0.45, underEyePearl: 0.45 },
    },
    eyeliner: {
      hex: '#3A2A26',
      geometry: { linerStyle: 'classic_winged', thickness: 0.05, length: 0.1, angle: 10, linerSoftness: 0.4 },
      overrides: { coverageMultiplier: 0.4, linerTaper: 0.9 },
    },
    mascara: {
      hex: '#1E1816',
      geometry: {
        length: 1.55, lashCount: 22, lashSweep: 0.12, lashClump: 0.35, lashFan: 38, lashJitter: 0.9, lashWidth: 0.5,
        lowerCount: 8, lowerLen: 2, lowerAlpha: 2.2,
      },
      overrides: { coverageMultiplier: 0.5, lashCurl: 1 },
    },
    brow: { hex: '#A88878', overrides: { coverageMultiplier: 0.55 } },
    lip: {
      hex: '#A8586A',
      geometry: { centerHighlight: 0.22, overlip: 0.02 },
      overrides: {
        coverageMultiplier: 0.45, lipColor: 0.9, lipGradient: 1, lipGloss: 2.6, skinAdapt: 0.1, skinWarmth: 0,
        material: { roughness: 0.04, specular: 2.0 },
      },
    },
  },
  // 설윤 뿌까: pink-white even skin, a soft flush toward the outer cheeks, glossy lips close to the bare lip colour,
  // a long thin wing and fine brown lashes (research/look6, finished frame e1gSkUdG6Bo_0002_final).
  e1gSkUdG6Bo: {
    // Real-device feedback (11-14): keep facial hair, shadows and skin texture, no patchy sampling near features. 11-14 balance:
    // the skin is evened by frequency separation (texture kept) instead of covered; blush and lip carry visible colour by colour
    // blend; the glow only lights raised points (local-contrast mask). The AR look strength slider scales all of it.
    // 11-17 bare/final pair fit (research/look6/pair_fit.py on the user's bare photo of the same face): face ΔE2000 4.12 -> 3.27
    // (bare -> final itself is 3.30). The final skin is only ~4% brighter, so coverage stays low and the evening does the work;
    // the glow lit pores as white specks and is off; the lip barely changes colour from the bare lip, the gloss carries it;
    // the wing is long, thin and drops slightly; lashes are fine and brown with a brown lower lash line.
    foundation: { overrides: { coverageMultiplier: 0.2, skinEven: 1, skinWide: 0, lightAdapt: 0.7, toneMap: 0.55, skin: { tint: '#EFC9D2', tone: 0.1, clean: 0.3 } } },
    blush: {
      hex: '#E46F8C',
      geometry: { blushPlacement: 'side', blushSize: 1.2, blushSoftness: 1 },
      overrides: { coverageMultiplier: 0.5, softLight: 2, blushColor: 0.8, skinAdapt: 0.6, skinWarmth: 0.28, lightAdapt: 0.7 },
    },
    highlighter: {
      hex: '#E3C6CA',
      geometry: { areas: ['nose_bridge', 'chin', 'under_eye'] },
      overrides: { coverageMultiplier: 0.8 },
    },
    contour: { hex: '#AE9598', overrides: { coverageMultiplier: 0.45 } },
    eyeshadow: {
      hex: '#F0C8C8',
      hexTo: '#8E6A66',
      geometry: { innerPoint: { hex: '#FBE8ED', a1: 0.1, radius: 0.06 } },
      overrides: { coverageMultiplier: 0.45, underEyePearl: 0.3 },
    },
    // 11-17 device: length 0.5 + hard edge read as a floating upward triangle on other faces. Keep a short soft
    // extension of the lash line (video final is a blended brown line, not a sharp cat-eye sticker).
    eyeliner: { hex: '#3A2A26', geometry: { length: 0.2, thickness: 0.04, angle: -8, linerSoftness: 0.5 }, overrides: { coverageMultiplier: 0.45, linerTaper: 1 } },
    mascara: {
      hex: '#3B2A24',
      geometry: { length: 1.7, lashCount: 26, lashSweep: 0.3, lashClump: 0.12, lashFan: 45, lashJitter: 0.8, lashWidth: 0.5, lowerCount: 8, lowerLen: 1.8 },
      overrides: { coverageMultiplier: 0.5, lashCurl: 1 },
    },
    brow: { overrides: { coverageMultiplier: 0.45 } },
    lip: {
      hex: '#B0686B',
      geometry: { centerHighlight: 0.2, overlip: 0.025, peakOverdraw: 0.018 },
      overrides: {
        coverageMultiplier: 0.3, lipColor: 0.2, lipGradient: 0.45, lipGloss: 2, skinAdapt: 0.8, skinWarmth: 0.28, lightAdapt: 0.7,
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
