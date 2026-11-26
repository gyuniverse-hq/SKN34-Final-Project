import type { ColorSwatch } from './nearbyColors';
import type { Language } from '@/lib/i18n/languages';
import type { ZoneSelection } from '@/store/makeupStore';
import type { Product } from '@/types';

const KEYWORD_LIMIT = 24;
const KEYWORD_LENGTH = 80;
const HEADER_LIMIT = 4096;
const PALETTE_RADIUS = 3;
const UNSUPPORTED_KEYWORD = /[<>\r\n]/;

/** Use the current swatch and nearby chips, plus products actually worn in this AR visit. */
export function arVoiceKeywords(
  products: readonly Product[],
  palette: readonly ColorSwatch[],
  center: number,
  selections: readonly (ZoneSelection | null | undefined)[],
): string[] {
  const worn: ColorSwatch[] = [];
  for (const selection of selections) {
    if (!selection) continue;
    const product = products.find(item => item.id === selection.productId);
    const shade = product?.shades.find(item => item.id === selection.shadeId);
    if (product && shade) worn.push({ product, shade });
  }

  const nearby = palette.slice(Math.max(0, center - PALETTE_RADIUS), center + PALETTE_RADIUS + 1);
  const focus = palette[center];
  const swatches = focus ? [focus, ...worn, ...nearby] : worn;
  return swatches.flatMap(({ product, shade }) => [product.brand, product.nameKo || product.name, shade.name]);
}

export function encodeArVoiceContext(language: Language, keywords: readonly string[]): string {
  const selected = new Map<string, string>();
  const encode = () => encodeURIComponent(JSON.stringify({ language, keywords: [...selected.values()] }));
  for (const term of keywords) {
    const normalized = term.normalize('NFKC');
    if (UNSUPPORTED_KEYWORD.test(normalized)) continue;
    const value = normalized.trim();
    const key = value.toLowerCase().replace(/\s+/g, '');
    if (!key || value.length > KEYWORD_LENGTH || selected.has(key)) continue;
    selected.set(key, value);
    if (encode().length > HEADER_LIMIT) selected.delete(key);
    if (selected.size === KEYWORD_LIMIT) break;
  }
  return encode();
}
