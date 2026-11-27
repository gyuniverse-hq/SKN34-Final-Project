import { useMemo } from 'react';
import { resolveShade } from '@/lib/catalog';
import { useProductOptions, useProductsByIds } from '@/lib/queries';
import { cartLineKey, useCartStore } from '@/store/cartStore';
import type { CartItem, Product, ProductOption } from '@/types';
import type { CartLineView } from '@/types/view';

export type CartLine = CartLineView & { product: Product };

export function buildCartLines(items: CartItem[], products: Product[] | undefined, options: ProductOption[] = []): CartLineView[] {
  const byId = new Map((products ?? []).map((p) => [p.id, p]));
  return items.map((item) => {
    const product = byId.get(item.productId);
    if (item.optionId) {
      const option = options.find(o => o.productId === item.productId && o.optionId === item.optionId);
      return { key: cartLineKey(item), item, product, option,
        availability: !product ? 'product_unavailable' as const : option ? 'available' as const : 'option_unavailable' as const,
        priceUnknown: !option || option.priceKRW === null,
        lineTotal: option?.priceKRW != null ? option.priceKRW * item.quantity : 0 };
    }
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

  const optionQueries = useProductOptions(items.filter((i): i is CartItem & { optionId: string } => !!i.optionId));
  const allLines = useMemo(() => buildCartLines(items, products.data, optionQueries.data), [items, products.data, optionQueries.data]);
  const lines = useMemo(
    () => allLines.filter((l): l is CartLine => l.availability === 'available' && !!l.product),
    [allLines]
  );
  const unavailable = useMemo(() => allLines.filter((l) => l.availability !== 'available'), [allLines]);

  const total = lines.reduce((sum, l) => sum + l.lineTotal, 0);
  return { items, allLines, lines, unavailable, total, query: { ...products, isPending: products.isPending || optionQueries.isPending } };
}
