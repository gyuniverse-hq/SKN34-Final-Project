import type { Href } from 'expo-router';
import type { MakeupZone, ProductCategory, SkinConcern } from '@/types';

/** Route params carry IDs only. Every screen builds and reads them through these helpers. */

export const MAKEUP_ZONES: readonly MakeupZone[] = [
  'lip',
  'blush',
  'eyeshadow',
  'eyeliner',
  'mascara',
  'highlighter',
  'contour',
  'brow',
  'foundation',
];
export const PRODUCT_CATEGORIES: readonly ProductCategory[] = ['lip', 'cheek', 'eye', 'base', 'skincare', 'suncare'];
export const SKIN_CONCERNS: readonly SkinConcern[] = [
  'dryness',
  'oiliness',
  'sensitivity',
  'blemish',
  'pores',
  'pigmentation',
  'wrinkles',
];
export type SearchSource = 'home' | 'skin';
export type LoginReturnTo = 'checkout';

type RawParam = string | string[] | undefined;

/** Same limit as the backend's id columns. */
const ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;

/** First value of a route param, trimmed; expo-router passes arrays for repeated keys. */
export function paramValue(value: RawParam): string | undefined {
  const first = Array.isArray(value) ? value[0] : value;
  const trimmed = first?.trim();
  return trimmed ? trimmed : undefined;
}

export function parseId(value: RawParam): string | undefined {
  const v = paramValue(value);
  return v && ID_PATTERN.test(v) ? v : undefined;
}

export function parseZone(value: RawParam): MakeupZone | undefined {
  const v = paramValue(value);
  return MAKEUP_ZONES.find((z) => z === v);
}

export function parseCategory(value: RawParam): ProductCategory | undefined {
  const v = paramValue(value);
  return PRODUCT_CATEGORIES.find((c) => c === v);
}

/** Known concerns only, deduplicated, in canonical order (stable query keys). */
export function parseConcerns(value: RawParam): SkinConcern[] {
  const parts = new Set((paramValue(value) ?? '').split(',').map((s) => s.trim()));
  return SKIN_CONCERNS.filter((c) => parts.has(c));
}

/** AR intensity, 0..1. */
export function parseIntensity(value: RawParam): number | undefined {
  const v = paramValue(value);
  if (!v) return undefined;
  const n = Number(v);
  return Number.isFinite(n) && n >= 0 && n <= 1 ? n : undefined;
}

export function parseSearchSource(value: RawParam): SearchSource | undefined {
  const v = paramValue(value);
  return v === 'home' || v === 'skin' ? v : undefined;
}

export function parseLoginReturnTo(value: RawParam): LoginReturnTo | undefined {
  return paramValue(value) === 'checkout' ? 'checkout' : undefined;
}

export function parseFlag(value: RawParam): boolean {
  return paramValue(value) === '1';
}

function compact(params: Record<string, string | undefined>): Record<string, string> {
  return Object.fromEntries(Object.entries(params).filter((e): e is [string, string] => !!e[1]));
}

export function productHref(productId: string, shadeId?: string): Href {
  return { pathname: '/product/[id]', params: compact({ id: productId, shade: shadeId }) } as Href;
}

export function lookHref(lookId: string): Href {
  return { pathname: '/look/[id]', params: { id: lookId } };
}

export function idolLookHref(lookId: string): Href {
  return { pathname: '/idol-look/[id]', params: { id: lookId } };
}

export function celebrityHref(id: string): Href {
  return { pathname: '/celebrities/[id]', params: { id } } as Href;
}

export function arHref(options: { productId?: string; shadeId?: string; compare?: boolean } = {}): Href {
  return {
    pathname: '/ar',
    params: compact({
      productId: options.productId,
      shadeId: options.productId ? options.shadeId : undefined,
      compare: options.compare ? '1' : undefined,
    }),
  } as Href;
}

export function recommendationsHref(options: {
  productId: string;
  shadeId: string;
  zone?: MakeupZone;
  intensity?: number;
}): Href {
  return {
    pathname: '/recommendations',
    params: compact({
      productId: options.productId,
      shadeId: options.shadeId,
      zone: options.zone,
      intensity: options.intensity === undefined ? undefined : options.intensity.toFixed(2),
    }),
  } as Href;
}

export function searchHref(options: {
  q?: string;
  category?: ProductCategory;
  concerns?: SkinConcern[];
  source?: SearchSource;
} = {}): Href {
  const concerns = options.concerns?.length ? SKIN_CONCERNS.filter((c) => options.concerns!.includes(c)) : [];
  return {
    pathname: '/search',
    params: compact({
      q: options.q?.trim() || undefined,
      category: options.category,
      concerns: concerns.length ? concerns.join(',') : undefined,
      source: options.source,
    }),
  } as Href;
}

export function externalLinkHref(productId: string, link: string): Href {
  return { pathname: '/external-link', params: { productId, link } } as Href;
}

export function loginHref(returnTo?: LoginReturnTo): Href {
  return { pathname: '/login', params: compact({ returnTo }) } as Href;
}

/** `verifyEmail` opens the code step for an account that signed up but never confirmed. */
export function signupHref(options: { returnTo?: LoginReturnTo; verifyEmail?: string } = {}): Href {
  return {
    pathname: '/signup',
    params: compact({
      returnTo: options.returnTo,
      email: options.verifyEmail,
      verify: options.verifyEmail ? '1' : undefined,
    }),
  } as Href;
}
