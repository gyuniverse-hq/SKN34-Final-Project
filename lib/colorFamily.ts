/**
 * Rough color family of a shade from its hex, for the AR screen's filter chips only.
 * CIELAB lightness L, chroma C and hue angle h (degrees). Shade hexes are mostly estimates
 * (measureMethod "estimated"), so this is a browsing aid, never a product claim or a diagnosis.
 */
export type ColorFamily = 'red' | 'coral' | 'pink' | 'berry' | 'nude' | 'brown';

export const COLOR_FAMILIES: ColorFamily[] = ['red', 'coral', 'pink', 'berry', 'nude', 'brown'];

function toLinear(c: number): number {
  const v = c / 255;
  return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
}

export function hexToLab(hex: string): { L: number; a: number; b: number } {
  const n = parseInt(hex.replace('#', ''), 16) || 0;
  const r = toLinear((n >> 16) & 255), g = toLinear((n >> 8) & 255), b = toLinear(n & 255);
  // sRGB D65 → XYZ, normalized by the D65 white point.
  const x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047;
  const y = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  const z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883;
  const f = (t: number) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116);
  const fx = f(x), fy = f(y), fz = f(z);
  return { L: 116 * fy - 16, a: 500 * (fx - fy), b: 200 * (fy - fz) };
}

export function colorFamily(hex: string): ColorFamily {
  const { L, a, b } = hexToLab(hex);
  const C = Math.hypot(a, b);
  const h = ((Math.atan2(b, a) * 180) / Math.PI + 360) % 360;
  // Muted shades: nude when light, brown when dark.
  if (C < 22 || (C < 28 && L >= 55) || (C < 32 && L >= 65)) return L >= 50 ? 'nude' : 'brown';
  // Orange side of red.
  if (h >= 40 && h <= 90) return L < 40 ? 'brown' : 'coral';
  if (h >= 25 && h < 40) {
    if (L < 32 && C < 45) return 'brown';
    return L >= 62 ? 'coral' : 'red';
  }
  // Blue side of red (pink, plum).
  return L < 42 ? 'berry' : 'pink';
}
