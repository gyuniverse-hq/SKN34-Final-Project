import type { ApplicationProfileOverrides, Product, Shade } from '@/types';

/**
 * Product AR only: per-SKU lip finish overrides (hex unchanged).
 * Key = `${productId}:${shadeId}`. Missing key → texture MATERIALS defaults.
 * Eval panel `lip-01-3ce-murmuring` maps to catalog oy-a000000148167 / 머머링.
 */
export const PRODUCT_LIP_FINISHES: Readonly<Record<string, ApplicationProfileOverrides>> = {
  // 3CE Soft Matte Lipstick · Murmuring — soft powder build, low shine (bare/real panel).
  'oy-a000000148167:a000000148167-017': {
    coverageMultiplier: 0.9,
    material: {
      a1: 0.52,
      roughness: 0.88,
      specular: 0.22,
      detail: 1.05,
      translucent: 0.05,
      glossScale: 0.2,
      overlay: 0.12,
      opacity: 0.92,
      cavity: 1.6,
    },
  },
};

export function productLipFinishKey(productId: string, shadeId: string) {
  return `${productId}:${shadeId}`;
}

/** Lip colour try-on only; care layers and other zones stay on texture defaults. */
export function productLipFinishFor(
  product: Pick<Product, 'id' | 'makeupZone'>,
  shade: Pick<Shade, 'id'>,
): ApplicationProfileOverrides | undefined {
  if (product.makeupZone !== 'lip') return undefined;
  const key = productLipFinishKey(product.id, shade.id);
  return Object.prototype.hasOwnProperty.call(PRODUCT_LIP_FINISHES, key)
    ? PRODUCT_LIP_FINISHES[key]
    : undefined;
}
