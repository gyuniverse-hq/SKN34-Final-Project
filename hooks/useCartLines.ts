import { useMemo } from 'react';
import { resolveShade } from '@/lib/catalog';
import { useProductsByIds } from '@/lib/queries';
import { cartLineKey, useCartStore } from '@/store/cartStore';
import type { CartItem, Product } from '@/types';
import type { CartLineView } from '@/types/view';

export type CartLine = CartLineView & { product: Product };

export function buildCartLines(items: CartItem[], products: Product[] | undefined): CartLineView[] {
  const byId = new Map((products ?? []).map((p) => [p.id, p]));
  return items.map((item) => {
    const product = byId.get(item.productId);
    const { availability, shade } = resolveShade(product, item.shadeId);
    const lineTotal = product && availability === 'available' ? product.priceKRW * item.quantity : 0;
    return { key: cartLineKey(item), item, availability, product, shade, lineTotal };
  });
}

/**
 * Joins persisted cart items (product + exact shade) with live catalog data. Lines whose product
 * or shade disappeared stay visible as unavailable so the user can see and remove them.
 */
export function useCartLines() {
  const items = useCartStore((s) => s.items);
  const products = useProductsByIds(items.map((i) => i.productId));

  const allLines = useMemo(() => buildCartLines(items, products.data), [items, products.data]);
  const lines = useMemo(
    () => allLines.filter((l): l is CartLine => l.availability === 'available' && !!l.product),
    [allLines]
  );
  const unavailable = useMemo(() => allLines.filter((l) => l.availability !== 'available'), [allLines]);

  const total = lines.reduce((sum, l) => sum + l.lineTotal, 0);
  return { items, allLines, lines, unavailable, total, query: products };
}
