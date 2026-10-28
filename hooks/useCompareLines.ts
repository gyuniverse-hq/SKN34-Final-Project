import { useMemo } from 'react';
import { resolveShade } from '@/lib/catalog';
import { useProductsByIds } from '@/lib/queries';
import { useCompareStore } from '@/store/compareStore';
import type { CompareLineView } from '@/types/view';

export function useCompareLines() {
  const items = useCompareStore((s) => s.items);
  const products = useProductsByIds(items.map((i) => i.productId));
  const lines = useMemo<CompareLineView[]>(() => {
    const byId = new Map((products.data ?? []).map((p) => [p.id, p]));
    return items.map((item) => {
      const product = byId.get(item.productId);
      return { item, product, ...resolveShade(product, item.shadeId) };
    });
  }, [items, products.data]);
  return { items, lines, query: products };
}
