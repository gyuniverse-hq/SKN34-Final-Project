import { hexToLab } from '@/lib/colorFamily';
import type { Product, Shade } from '@/types';

/** Skin color measured by the AR page (CIE Lab), with the light estimate's confidence 0..1. */
export interface SkinTone {
  L: number;
  a: number;
  b: number;
  conf: number;
}

export interface ShadeMatch {
  product: Product;
  shade: Shade;
  /** CIE76 color difference to the measured skin (smaller = closer). */
  deltaE: number;
  /** Shade lightness minus skin lightness (L*): positive = the shade is lighter than the skin. */
  deltaL: number;
}

/** Below this light confidence the color cast of the room is not removed, so no suggestion is shown. */
export const MIN_TONE_CONF = 0.3;

/**
 * Foundation shades from the given options, closest to the measured skin color first. Only the shades passed in are
 * ranked (no invented products). A color-based reference only: the camera's exposure and white balance move the
 * measurement, and the undertone is not judged.
 */
export function rankFoundationShades(tone: SkinTone, options: { product: Product; shade: Shade }[]): ShadeMatch[] {
  return options
    .map(({ product, shade }) => {
      const lab = hexToLab(shade.hex);
      return {
        product,
        shade,
        deltaE: Math.hypot(lab.L - tone.L, lab.a - tone.a, lab.b - tone.b),
        deltaL: lab.L - tone.L,
      };
    })
    .sort((x, y) => x.deltaE - y.deltaE);
}

/** Parses the page's `skin_tone` message; null when it is malformed. */
export function parseSkinTone(message: { lab?: unknown; conf?: unknown }): SkinTone | null {
  const lab = message.lab;
  if (!Array.isArray(lab) || lab.length !== 3 || !lab.every((v) => typeof v === 'number' && Number.isFinite(v))) return null;
  const conf = typeof message.conf === 'number' && Number.isFinite(message.conf) ? message.conf : 0;
  return { L: lab[0], a: lab[1], b: lab[2], conf: Math.max(0, Math.min(1, conf)) };
}
