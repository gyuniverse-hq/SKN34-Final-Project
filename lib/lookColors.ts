import type { CelebLook } from '@/types';

export type ColorFamily = 'rosy' | 'coral' | 'red' | 'mute' | 'brown';

export const COLOR_FAMILIES: readonly ColorFamily[] = ['rosy', 'coral', 'red', 'mute', 'brown'];

/** Representative swatch shown on each filter chip. */
export const COLOR_FAMILY_SWATCH: Record<ColorFamily, string> = {
  rosy: '#C9636F',
  coral: '#E58C7A',
  red: '#B3202F',
  mute: '#A88B8B',
  brown: '#8A5A44',
};

function hexToHsl(hex: string): { h: number; s: number; l: number } | null {
  const match = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!match) return null;
  const value = parseInt(match[1], 16);
  const r = ((value >> 16) & 255) / 255;
  const g = ((value >> 8) & 255) / 255;
  const b = (value & 255) / 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;
  const d = max - min;
  if (d === 0) return { h: 0, s: 0, l };
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  const h = max === r ? (g - b) / d + (g < b ? 6 : 0) : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return { h: h * 60, s, l };
}

/** Buckets a makeup colour into a shopper-facing family; null for hues outside warm/pink makeup tones. */
export function colorFamilyOf(hex: string): ColorFamily | null {
  const hsl = hexToHsl(hex);
  if (!hsl) return null;
  const { h, s, l } = hsl;
  if ((h >= 345 || h < 10) && s >= 0.6 && l <= 0.55) return 'red';
  if (h >= 8 && h < 50 && l < 0.4 && s >= 0.15) return 'brown';
  if (s < 0.25) return 'mute';
  if (h >= 280 || h < 2) return 'rosy';
  if (h < 50) return 'coral';
  return null;
}

/** A look's family follows its most visible zone: lip, then blush, then eyeshadow. */
export function lookColorFamily(look: CelebLook): ColorFamily | null {
  const zone = look.makeup.lip ?? look.makeup.blush ?? look.makeup.eyeshadow;
  return zone ? colorFamilyOf(zone.hex) : null;
}

/** Families present in the given looks, in display order, so no chip leads to an empty result. */
export function availableColorFamilies(looks: readonly CelebLook[]): ColorFamily[] {
  const present = new Set(looks.map(lookColorFamily));
  return COLOR_FAMILIES.filter((family) => present.has(family));
}
