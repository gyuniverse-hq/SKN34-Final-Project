/** Screen view models: API data joined with on-device state. Not part of the HTTP contract. */
import type { CartItem, Product, ProductOption, Shade, SimilarReason } from './index';

/** Whether a saved product + shade still exists in the live catalog. */
export type CatalogAvailability = 'available' | 'shade_unavailable' | 'product_unavailable' | 'option_unavailable';

export interface CartLineView {
  key: string;
  item: CartItem;
  availability: CatalogAvailability;
  /** Missing when the product is no longer in the catalog. */
  product?: Product;
  shade?: Shade;
  option?: ProductOption;
  priceUnknown?: boolean;
  lineTotal: number;
}

export interface CompareItem {
  productId: string;
  shadeId?: string;
}

export interface CompareLineView {
  item: CompareItem;
  availability: CatalogAvailability;
  product?: Product;
  shade?: Shade;
}

export interface RecommendationView {
  product: Product;
  shade: Shade;
  deltaE: number;
  reasons: SimilarReason[];
}
