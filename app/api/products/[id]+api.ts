import { errorResponse, json } from '@/server/lib/http';
import { getProduct } from '@/server/services/catalogService';

export async function GET(_request: Request, { id }: Record<string, string>) {
  const product = await getProduct(id);
  if (!product) return errorResponse(404, 'Product not found', 'not_found');
  return json({ product }, { maxAgeSeconds: 300 });
}
