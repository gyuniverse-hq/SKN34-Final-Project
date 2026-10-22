import { errorResponse, json } from '@/server/lib/http';
import { getProductOffers } from '@/server/services/offerService';

export async function GET(_request: Request, { id }: Record<string, string>) {
  try {
    const result = await getProductOffers(id);
    if (!result) return errorResponse(404, 'Product not found', 'not_found');
    return json(result, result.configured ? { maxAgeSeconds: 1800 } : undefined);
  } catch (error) {
    console.error('[offers]', error);
    return errorResponse(502, 'Shopping search is temporarily unavailable', 'upstream_error');
  }
}
