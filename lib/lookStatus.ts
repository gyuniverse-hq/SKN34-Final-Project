import type { IdolLook, LookProductStatus } from '@/types';
import type { TranslationKey } from './i18n';

export type StatusTone = 'brand' | 'neutral' | 'success' | 'warning';

/** Product-mapping badge for a YouTube look. Unreviewed videos never claim products. */
export function idolLookMapping(look: IdolLook): { key: TranslationKey; tone: StatusTone; count: number } {
  const count = look.products.length;
  if (look.video.productMappingStatus === 'mapped' && count > 0) return { key: 'idol.mapping.mapped', tone: 'brand', count };
  if (look.video.productMappingStatus === 'no_verified_products') return { key: 'idol.mapping.empty', tone: 'neutral', count };
  return { key: 'idol.mapping.registered', tone: 'warning', count };
}

/** Verification badge per product: only `verified_used` may say the video used it. */
export function lookProductStatus(status: LookProductStatus): { key: TranslationKey; tone: StatusTone } {
  if (status === 'verified_used') return { key: 'idol.verified', tone: 'success' };
  if (status === 'similar') return { key: 'badge.vishuePick', tone: 'brand' };
  return { key: 'idol.unverified', tone: 'warning' };
}
