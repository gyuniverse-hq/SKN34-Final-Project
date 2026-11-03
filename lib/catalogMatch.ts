import { parseId } from '@/lib/routes';
import { isArPaintZone } from '@/store/makeupStore';
import type { Product, Shade, StyleLookProduct, VideoProductMapping } from '@/types';

export function normalizeCatalogText(value: string): string {
  return value.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, '');
}

function brandKey(product: Product): string {
  return normalizeCatalogText(product.brand);
}

function nameKey(product: Product): string {
  return normalizeCatalogText(product.nameKo) || normalizeCatalogText(product.name);
}

/** Exact brand, and the listed name must appear in full in the catalog name. Short labels are skipped. */
export function matchCatalogProduct(
  listed: Pick<StyleLookProduct, 'brand' | 'name'>,
  products: Product[]
): Product | undefined {
  const brand = normalizeCatalogText(listed.brand);
  const name = normalizeCatalogText(listed.name);
  if (brand.length < 2 || name.length < 4) return undefined;
  return products.find((product) => {
    if (brandKey(product) !== brand) return false;
    const catalogName = nameKey(product);
    return catalogName === name || catalogName.includes(name);
  });
}

/** Content verification and catalog validity are separate requirements for automatic try-on. */
export function resolveVerifiedCatalogSelection(
  mapping: VideoProductMapping,
  products: Product[]
): { product: Product; shade: Shade; zone: NonNullable<Product['makeupZone']>; texture: NonNullable<Product['texture']> } | undefined {
  if (mapping.mappingVerified !== true || !parseId(mapping.catalogProductId) || !parseId(mapping.catalogShadeId)) return undefined;
  const product = products.find((candidate) => candidate.id === mapping.catalogProductId);
  if (!product?.makeupZone || !product.texture || !isArPaintZone(product.makeupZone)) return undefined;
  const shade = product.shades.find((candidate) => candidate.id === mapping.catalogShadeId);
  if (!shade || shade.measureMethod === 'placeholder' || shade.colorSource === 'placeholder') return undefined;
  return { product, shade, zone: product.makeupZone, texture: product.texture };
}
