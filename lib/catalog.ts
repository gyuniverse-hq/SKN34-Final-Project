import type { Product, Shade } from '@/types';
import type { CatalogAvailability } from '@/types/view';

/** Resolves a saved product + shade against live catalog data. */
export function resolveShade(
  product: Product | undefined,
  shadeId: string | undefined
): { availability: CatalogAvailability; shade?: Shade } {
  if (!product) return { availability: 'product_unavailable' };
  if (!shadeId) return { availability: 'available' };
  const shade = product.shades.find((s) => s.id === shadeId);
  return shade ? { availability: 'available', shade } : { availability: 'shade_unavailable' };
}

/** Shade the screen should show: the requested one if it exists, otherwise the first. */
export function pickShade(product: Product, shadeId: string | undefined): Shade | undefined {
  return product.shades.find((s) => s.id === shadeId) ?? product.shades[0];
}

export function canTryOn(product: Product): boolean {
  return !!product.makeupZone && product.shades.length > 0;
}
