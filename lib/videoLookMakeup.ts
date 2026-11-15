import { lookApplicationProfileFor } from '@/lib/applicationProfiles';
import { demoLookVideoId } from '@/lib/demoLookAr';
import { videoLookStyle } from '@/lib/videoLookStyles';
import type { ApplicationProfileOverrides, MakeupState, MakeupZone } from '@/types';

const LOOK_ZONES: MakeupZone[] = [
  'lip', 'blush', 'eyeshadow', 'eyeliner', 'mascara', 'highlighter', 'contour', 'brow', 'foundation',
];

/** Look strength slider range: 1 = the look's tuned values, lower = more natural, higher = more visible. */
export const LOOK_STRENGTH_MIN = 0.3;
export const LOOK_STRENGTH_MAX = 1.7;

const cap = (value: number | undefined, s: number, max: number) => (value === undefined ? undefined : Math.min(max, value * s));

/** Scales how much of the look is laid on (coverage and effect gains); colours and shapes stay. */
export function scaleLookOverrides(o: ApplicationProfileOverrides, strength: number): ApplicationProfileOverrides {
  const s = Math.min(LOOK_STRENGTH_MAX, Math.max(LOOK_STRENGTH_MIN, Number.isFinite(strength) ? strength : 1));
  if (s === 1) return o;
  const scaled: ApplicationProfileOverrides = { ...o };
  const set = <K extends keyof ApplicationProfileOverrides>(key: K, value: ApplicationProfileOverrides[K]) => {
    if (value !== undefined) scaled[key] = value;
  };
  set('coverageMultiplier', cap(o.coverageMultiplier ?? 1, s, 2));
  set('softLight', cap(o.softLight, s, 8));
  set('blushColor', cap(o.blushColor, s, 8));
  set('glow', cap(o.glow, s, 4));
  set('lipGloss', cap(o.lipGloss, s, 3));
  set('lipColor', cap(o.lipColor, s, 1));
  set('underEyePearl', cap(o.underEyePearl, s, 1));
  set('skinEven', cap(o.skinEven, s, 1));
  if (o.skin) scaled.skin = { ...o.skin, tone: Math.min(1, o.skin.tone * s), clean: Math.min(1, o.skin.clean * s) };
  return scaled;
}

/** Render-only look color: never alter the store, product shade, or selected item. */
export function videoLookMakeup(
  makeup: MakeupState,
  options: {
    fromVideo: boolean; cameraActive: boolean; fittingProduct: boolean; lookId: string | null; modified: MakeupZone[];
    /** Look strength slider (LOOK_STRENGTH_MIN..MAX, default 1); scales only the look's own finish. */
    strength?: number;
  },
): MakeupState {
  if (!options.fromVideo || !options.cameraActive || options.fittingProduct || !options.lookId) return makeup;
  const videoId = demoLookVideoId(options.lookId);
  let result = makeup;
  for (const zone of LOOK_ZONES) {
    const setting = makeup[zone];
    if (!setting || options.modified.includes(zone)) continue;
    const profile = lookApplicationProfileFor(videoId, zone);
    const style = videoLookStyle(videoId, zone);
    if (!profile?.lookHex && !style) continue;
    if (result === makeup) result = { ...makeup };
    let next = setting;
    if (profile?.lookHex) {
      next = {
        ...next, hex: profile.lookHex, applicationProfile: profile.overrides,
        ...(profile.geometry ? { geometry: { ...next.geometry, ...profile.geometry } } : {}),
      };
    }
    if (style) {
      next = {
        ...next,
        ...(style.hex ? { hex: style.hex } : {}),
        ...(style.hexTo ? { hexTo: style.hexTo } : {}),
        ...(style.geometry ? { geometry: { ...next.geometry, ...style.geometry } } : {}),
        ...(style.overrides ? {
          applicationProfile: { ...next.applicationProfile, ...scaleLookOverrides(style.overrides, options.strength ?? 1) },
        } : {}),
      };
    }
    result[zone] = next;
  }
  return result;
}
