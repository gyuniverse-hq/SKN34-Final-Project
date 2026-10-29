import { useMemo } from 'react';
import { useSimilarShades } from '@/lib/queries';
import type { SimilarShadesResponse } from '@/types';
import type { RecommendationView } from '@/types/view';

export function joinRecommendations(data: SimilarShadesResponse | undefined): RecommendationView[] {
  if (!data) return [];
  const byId = new Map(data.products.map((p) => [p.id, p]));
  return data.matches.flatMap((m) => {
    const product = byId.get(m.productId);
    const shade = product?.shades.find((s) => s.id === m.shadeId);
    return product && shade ? [{ product, shade, deltaE: m.deltaE, reasons: m.reasons }] : [];
  });
}

export function useSimilarRecommendations(productId: string | undefined, shadeId: string | undefined) {
  const query = useSimilarShades(productId, shadeId);
  const items = useMemo(() => joinRecommendations(query.data), [query.data]);
  return { query, items, source: query.data?.source };
}
