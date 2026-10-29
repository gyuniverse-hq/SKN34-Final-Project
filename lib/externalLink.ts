import type { ShoppingOffer } from '@/types';

/** Only plain https links leave the app. */
export function isSafeExternalUrl(value: string | undefined): value is string {
  if (!value || value.length > 2048) return false;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && !!url.hostname && !url.username && !url.password;
  } catch {
    return false;
  }
}

/** The route carries a link, but only a link from this product's own offers is honored. */
export function findOffer(offers: ShoppingOffer[] | undefined, link: string | undefined): ShoppingOffer | undefined {
  if (!isSafeExternalUrl(link)) return undefined;
  return offers?.find((o) => o.link === link);
}

export function hostnameOf(link: string): string {
  try {
    return new URL(link).hostname;
  } catch {
    return '';
  }
}
