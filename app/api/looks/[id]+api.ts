import { errorResponse, json } from '@/server/lib/http';
import { getLookWithProducts } from '@/server/services/catalogService';

export async function GET(_request: Request, { id }: Record<string, string>) {
  const result = await getLookWithProducts(id);
  if (!result) return errorResponse(404, 'Look not found', 'not_found');
  return json(result, { maxAgeSeconds: 300 });
}
