import type { Product, Shade, StyleLookProduct } from '@/types';

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

export function matchListedShade(product: Product, option: string): Shade | undefined {
  if (product.shades.length === 0) return undefined;
  const opt = normalizeCatalogText(option);
  if (opt.length < 2 || opt.includes('원문에명시')) return product.shades[0];
  return (
    product.shades.find((shade) => {
      const shadeName = normalizeCatalogText(shade.name);
      return shadeName === opt || shadeName.includes(opt) || opt.includes(shadeName);
    }) ?? product.shades[0]
  );
}
