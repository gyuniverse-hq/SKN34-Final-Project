import { errorResponse, json, stringParam } from '@/server/lib/http';
import { isCategory, listProducts } from '@/server/services/catalogService';

export async function GET(request: Request) {
  const url = new URL(request.url);
  const category = stringParam(url, 'category', 20);
  if (category && !isCategory(category)) {
    return errorResponse(400, 'Unknown category', 'invalid_category');
  }
  const idsParam = stringParam(url, 'ids', 2000);
  const ids = idsParam?.split(',').map((s) => s.trim()).filter(Boolean).slice(0, 50);

  const products = await listProducts({
    q: stringParam(url, 'q', 80),
    category: isCategory(category) ? category : undefined,
    ids,
  });
  return json({ products }, { maxAgeSeconds: 300 });
}
