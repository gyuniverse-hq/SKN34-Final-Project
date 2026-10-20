import { getProductSync } from '@/server/catalog';
import { errorResponse, json } from '@/server/http';
import { isNaverConfigured, searchOffers } from '@/server/naver';
import type { ProductOffers } from '@/types';

export async function GET(_request: Request, { id }: Record<string, string>) {
  const product = getProductSync(id);
  if (!product) return errorResponse(404, 'Product not found', 'not_found');

  if (!isNaverConfigured()) {
    return json<ProductOffers>({ configured: false, offers: [] });
  }
  try {
    const offers = await searchOffers(product.searchKeyword, 5);
    return json<ProductOffers>({ configured: true, offers }, { maxAgeSeconds: 1800 });
  } catch (error) {
    console.error('[offers]', error);
    return errorResponse(502, 'Shopping search is temporarily unavailable', 'upstream_error');
  }
}
