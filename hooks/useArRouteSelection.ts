import { useEffect, useRef } from 'react';
import { canTryOn, pickShade } from '@/lib/catalog';
import { useProduct } from '@/lib/queries';
import { useMakeupStore } from '@/store/makeupStore';

/**
 * Applies the product + shade from AR route params (product detail → "Try in AR") once per
 * selection, so later manual changes are not overwritten when the screen refocuses.
 */
export function useArRouteSelection(productId: string | undefined, shadeId: string | undefined) {
  const product = useProduct(productId);
  const applyShade = useMakeupStore((s) => s.applyShade);
  const applied = useRef<string | null>(null);
  const data = product.data;
  const shade = data ? pickShade(data, shadeId) : undefined;
  const tryOn = data ? canTryOn(data) : false;

  useEffect(() => {
    if (!data || !shade || !tryOn) return;
    const key = `${data.id}::${shade.id}`;
    if (applied.current === key) return;
    applied.current = key;
    applyShade(data, shade);
  }, [data, shade, tryOn, applyShade]);

  return {
    product,
    shade,
    shadeMissing: !!data && !!shadeId && shade?.id !== shadeId,
    notTryOn: !!data && !tryOn,
  };
}
