import { useMemo } from 'react';
import { useProductsByIds } from '@/lib/queries';
import { cartLineKey, useCartStore } from '@/store/cartStore';
import type { CartItem, Product, Shade } from '@/types';

export interface CartLine {
  key: string;
  item: CartItem;
  product: Product;
  shade?: Shade;
  lineTotal: number;
}

/** Joins persisted cart items with live catalog data. Unknown products are skipped. */
export function useCartLines() {
  const items = useCartStore((s) => s.items);
  const products = useProductsByIds(items.map((i) => i.productId));

  const lines = useMemo<CartLine[]>(() => {
    const byId = new Map((products.data ?? []).map((p) => [p.id, p]));
    return items.flatMap((item) => {
      const product = byId.get(item.productId);
      if (!product) return [];
      const shade = product.shades.find((s) => s.id === item.shadeId);
      return [{ key: cartLineKey(item), item, product, shade, lineTotal: product.priceKRW * item.quantity }];
    });
  }, [items, products.data]);

  const total = lines.reduce((sum, l) => sum + l.lineTotal, 0);
  return { items, lines, total, query: products };
}
