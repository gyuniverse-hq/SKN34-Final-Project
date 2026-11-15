/** sRGB / D65 and CIEDE2000, matching backend/api/app/services/color.py.
 * Keep separate from colorFamily's approximate Lab / legacy CIE76 look matching.
 */
export interface Lab { L: number; a: number; b: number }

export function hexToLabD65(hex: string): Lab | null {
  if (!/^#[0-9a-f]{6}$/i.test(hex)) return null;
  const linear = (offset: number) => {
    const c = Number.parseInt(hex.slice(offset, offset + 2), 16) / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  const r = linear(1), g = linear(3), b = linear(5);
  const f = (t: number) => t > (6 / 29) ** 3 ? Math.cbrt(t) : t / (3 * (6 / 29) ** 2) + 4 / 29;
  const fx = f((0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047);
  const fy = f(0.2126729 * r + 0.7151522 * g + 0.0721750 * b);
  const fz = f((0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / 1.08883);
  return { L: 116 * fy - 16, a: 500 * (fx - fy), b: 200 * (fy - fz) };
}

const radians = (degrees: number) => degrees * Math.PI / 180;
const hue = (a: number, b: number) => (Math.atan2(b, a) * 180 / Math.PI + 360) % 360;
export const labToLch = ({ L, a, b }: Lab) => ({ L, C: Math.hypot(a, b), h: hue(a, b) });
export const hueDifference = (from: number, to: number) => ((to - from + 540) % 360) - 180;

/** Sharma et al. (2005), kL = kC = kH = 1; inputs and result are unrounded. */
export function ciede2000(first: Lab, second: Lab): number {
  const cBar = (Math.hypot(first.a, first.b) + Math.hypot(second.a, second.b)) / 2;
  const g = 0.5 * (1 - Math.sqrt(cBar ** 7 / (cBar ** 7 + 25 ** 7)));
  const a1 = (1 + g) * first.a, a2 = (1 + g) * second.a;
  const c1 = Math.hypot(a1, first.b), c2 = Math.hypot(a2, second.b);
  const h1 = hue(a1, first.b), h2 = hue(a2, second.b);
  const dl = second.L - first.L, dc = c2 - c1;
  let dh = h2 - h1;
  if (c1 * c2 === 0) dh = 0;
  else if (dh > 180) dh -= 360;
  else if (dh < -180) dh += 360;
  const dH = 2 * Math.sqrt(c1 * c2) * Math.sin(radians(dh / 2));
  const lBar = (first.L + second.L) / 2, cpBar = (c1 + c2) / 2;
  let hBar = (h1 + h2) / 2;
  if (c1 * c2 === 0) hBar = h1 + h2;
  else if (Math.abs(h1 - h2) > 180) hBar += h1 + h2 < 360 ? 180 : -180;
  const t = 1 - 0.17 * Math.cos(radians(hBar - 30))
    + 0.24 * Math.cos(radians(2 * hBar)) + 0.32 * Math.cos(radians(3 * hBar + 6))
    - 0.20 * Math.cos(radians(4 * hBar - 63));
  const theta = 30 * Math.exp(-(((hBar - 275) / 25) ** 2));
  const rc = 2 * Math.sqrt(cpBar ** 7 / (cpBar ** 7 + 25 ** 7));
  const sl = 1 + 0.015 * (lBar - 50) ** 2 / Math.sqrt(20 + (lBar - 50) ** 2);
  const sc = 1 + 0.045 * cpBar, sh = 1 + 0.015 * cpBar * t;
  const rt = -Math.sin(radians(2 * theta)) * rc;
  return Math.sqrt((dl / sl) ** 2 + (dc / sc) ** 2 + (dH / sh) ** 2 + rt * (dc / sc) * (dH / sh));
}
