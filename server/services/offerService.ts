import { isNaverConfigured, searchOffers } from '@/server/clients/naverClient';
import { findProductById } from '@/server/repositories/catalogRepository';
import type { ProductOffers } from '@/types';

/** Online offers for a product, or `null` when the product does not exist. Throws on upstream failure. */
export async function getProductOffers(productId: string): Promise<ProductOffers | null> {
  const product = await findProductById(productId);
  if (!product) return null;
  if (!isNaverConfigured()) return { configured: false, offers: [] };
  const offers = await searchOffers(product.searchKeyword, 5);
  return { configured: true, offers };
}
