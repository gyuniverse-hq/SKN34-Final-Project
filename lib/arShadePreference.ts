import { colorFamily, COLOR_FAMILIES, type ColorFamily } from './colorFamily';
import { ciede2000, hexToLabD65, labToLch } from './colorDifference';
import type { ColorSwatch } from './nearbyColors';
import type { MakeupState, MakeupZone } from '@/types';

const LIGHTNESS = ['light', 'medium', 'deep'] as const;
const CHROMA = ['muted', 'medium', 'vivid'] as const;
export const LIP_TYPES = { lipstick:'립스틱', tint:'립틴트', gloss:'립글로스' } as const;
export interface ShadePreference {
  family?: ColorFamily;
  lightness?: typeof LIGHTNESS[number];
  chroma?: typeof CHROMA[number];
  lipType?: keyof typeof LIP_TYPES;
}

function optionalEnum<T extends string>(values: readonly T[], value: unknown): value is T | null | undefined {
  return value == null || values.some(item => item === value);
}

/** Null means an invalid argument. An omitted dimension places no constraint on the shade. */
export function readShadePreference(raw: Record<string, unknown>): ShadePreference | null {
  const { family, lightness, chroma, lipType } = raw;
  if (!optionalEnum(COLOR_FAMILIES, family) || !optionalEnum(LIGHTNESS, lightness) || !optionalEnum(CHROMA, chroma)
      || !optionalEnum(['lipstick','tint','gloss'] as const, lipType)) return null;
  return { family: family ?? undefined, lightness: lightness ?? undefined, chroma: chroma ?? undefined, lipType: lipType ?? undefined };
}

const FAMILY_CHIP: Record<ColorFamily, string> = {
  pink: '#ef79ab', red: '#bd343d', coral: '#f28b72', berry: '#913c68', nude: '#c49a88', brown: '#805342',
};
const TARGET_L = { light: 76, medium: 55, deep: 35 };
const TARGET_C = { muted: 24, medium: 46, vivid: 68 };

export function shadeTone(hex: string) {
  const lab = hexToLabD65(hex);
  if (!lab) return null;
  const { L, C } = labToLch(lab);
  return {
    lab, L, C,
    lightness: L >= 65 ? 'light' : L < 45 ? 'deep' : 'medium',
    chroma: C < 38 ? 'muted' : C >= 55 ? 'vivid' : 'medium',
  } as const;
}

export function usableShadeTone(item: ColorSwatch) {
  if (!item.product.texture || item.shade.measureMethod === 'placeholder' || item.shade.colorSource === 'placeholder') return null;
  return shadeTone(item.shade.hex);
}

/** Match cheeks to the visible lip when present. Otherwise coordinate the visible layers. */
export function pickForMakeup(items: ColorSwatch[], zone: MakeupZone, makeup: MakeupState) {
  if (zone !== 'lip' && zone !== 'blush' && zone !== 'eyeshadow') return {item:items.find(usableShadeTone), sources:[]};
  const sources = [];
  const mean = {L:0, a:0, b:0};
  let weight = 0;
  const lip = makeup.lip;
  const lipReference = zone === 'blush' && lip && lip.intensity > 0 ? hexToLabD65(lip.hex) : null;
  const parts = lipReference ? ['lip'] as const :
    ['lip','blush','eyeshadow','highlighter','contour','foundation','brow','eyeliner','mascara'] as const;
  for (const part of parts) {
    const layer = makeup[part];
    if (part === zone || !layer || layer.intensity <= 0) continue;
    const lab = lipReference ?? hexToLabD65(layer.hex);
    if (!lab) continue;
    const importance = part === 'lip' || part === 'blush' ? 4 : part === 'eyeshadow' ? 2 : 0.35;
    const w = layer.intensity * importance;
    mean.L += w * lab.L;
    mean.a += w * lab.a;
    mean.b += w * lab.b;
    weight += w;
    sources.push({zone:part, family:colorFamily(layer.hex), weight:w});
  }
  const bare = {lip:'#c47e87', blush:'#d99a9b', eyeshadow:'#ae8c7c'};
  let target = hexToLabD65(bare[zone])!;
  if (weight) {
    const blush = zone === 'blush';
    target = {L:blush ? Math.min(88, Math.max(58, mean.L/weight + 12)) : mean.L/weight,
      a:mean.a/weight * (blush ? 0.7 : 1), b:mean.b/weight * (blush ? 0.7 : 1)};
  }
  let item: ColorSwatch | undefined;
  let best = Infinity;
  for (const candidate of items) {
    const tone = usableShadeTone(candidate);
    if (!tone) continue;
    const distance = ciede2000(tone.lab, target);
    if (distance < best) { best = distance; item = candidate; }
  }
  return {item, sources:sources.sort((a,b) => b.weight-a.weight).map(({zone,family}) => ({zone,family}))};
}

export function rankShadePreferences(items: ColorSwatch[], {family, lightness, chroma}: ShadePreference) {
  const targetL = lightness && TARGET_L[lightness];
  const targetC = chroma && TARGET_C[chroma];
  const chip = family && hexToLabD65(FAMILY_CHIP[family]);
  // Preserve the reference hue while replacing only the requested L* or C*.
  const scale = chip && targetC !== undefined ? targetC / Math.hypot(chip.a, chip.b) : 1;
  const target = chip && { L: targetL ?? chip.L, a: chip.a * scale, b: chip.b * scale };
  const ranked = [];
  for (const item of items) {
    const tone = usableShadeTone(item);
    if (!tone || (family && colorFamily(item.shade.hex) !== family) ||
        (lightness && tone.lightness !== lightness) || (chroma && tone.chroma !== chroma)) continue;
    const distance = target ? ciede2000(target, tone.lab) :
      Math.hypot(tone.L - (targetL ?? tone.L), tone.C - (targetC ?? tone.C));
    ranked.push({ item, distance });
  }
  return ranked.sort((a, b) => a.distance - b.distance).map(row => row.item);
}
