/** Domain types shared by the app (client) and API routes (server). */

export type ProductCategory = 'lip' | 'cheek' | 'eye' | 'base' | 'skincare' | 'suncare';

export type MakeupZone = 'lip' | 'blush' | 'eyeshadow';

export type Texture = 'matte' | 'velvet' | 'glossy' | 'satin' | 'sheer' | 'cream' | 'shimmer';

export interface Shade {
  id: string;
  name: string;
  hex: string;
}

export interface Product {
  id: string;
  brand: string;
  name: string;
  /** Korean product name shown to store staff in the in-store shopping list. */
  nameKo: string;
  category: ProductCategory;
  /** Null for products that can't be tried on (skincare, base). */
  makeupZone: MakeupZone | null;
  texture: Texture;
  /** Reference retail price in KRW. Live prices come from /api/products/:id/offers. */
  priceKRW: number;
  volume: string;
  shades: Shade[];
  description: string;
  keyIngredients: string[];
  tags: string[];
  imageUrl: string;
  /** Query used to look the product up on shopping search providers. */
  searchKeyword: string;
}

export interface LookItem {
  productId: string;
  shadeId?: string;
  step: 'prep' | 'base' | 'eyes' | 'cheeks' | 'lips';
}

export interface ZoneSetting {
  hex: string;
  /** 0..1 */
  intensity: number;
  texture: Texture;
}

export interface MakeupState {
  lip: ZoneSetting | null;
  blush: ZoneSetting | null;
  eyeshadow: ZoneSetting | null;
}

export interface CelebLook {
  id: string;
  title: string;
  /** Inspiration label, e.g. "Inspired by K-pop idol stage looks". Not an endorsement. */
  inspiration: string;
  description: string;
  thumbnailUrl: string;
  /** YouTube search query used to fetch live tutorials for this look. */
  tutorialQuery: string;
  items: LookItem[];
  makeup: MakeupState;
  tags: string[];
}

export interface Store {
  id: string;
  name: string;
  address: string;
  district: string;
  lat: number;
  lng: number;
  hours: string;
  phone?: string;
  pickupAvailable: boolean;
}

export interface CartItem {
  productId: string;
  shadeId?: string;
  quantity: number;
  addedFromLookId?: string;
}

export interface ShoppingListLine {
  productId: string;
  shadeId?: string;
  quantity: number;
  unitPriceKRW: number;
  brand: string;
  name: string;
  nameKo: string;
  shadeName?: string;
}

/** Saved in-store shopping list (shown to store staff). Stored on device only. */
export interface ShoppingList {
  id: string;
  createdAt: string;
  storeId?: string;
  lines: ShoppingListLine[];
  totalKRW: number;
}

export interface YoutubeVideo {
  videoId: string;
  title: string;
  channelTitle: string;
  thumbnailUrl: string;
  publishedAt: string;
}

/** A verified YouTube-backed look. Product data stays empty until an administrator verifies it. */
export type VideoAnalysisStatus = 'registered' | 'metadata_unavailable' | 'metadata_ready';
export type ProductMappingStatus = 'unreviewed' | 'no_verified_products' | 'mapped';
export type LookProductStatus = 'verified_used' | 'unverified' | 'similar';

export interface IdolVideo {
  id: string;
  videoId: string;
  youtubeUrl: string;
  startSeconds: number;
  title: string;
  channelName: string;
  thumbnailUrl: string;
  description: string | null;
  publishedAt: string | null;
  makeupLookId: string;
  analysisStatus: VideoAnalysisStatus;
  productMappingStatus: ProductMappingStatus;
}

export interface IdolLookProduct {
  id: string;
  makeupZone: MakeupZone;
  status: LookProductStatus;
  productId: string | null;
  shadeId: string | null;
  sourceType: string | null;
  sourceUrl: string | null;
  evidenceText: string | null;
  verified: boolean;
  similarityScore: number | null;
  recommendationReason: string | null;
}

export interface IdolLook {
  id: string;
  displayName: string;
  styleDescription: string;
  isPublished: boolean;
  video: IdolVideo;
  products: IdolLookProduct[];
  arSettings: MakeupState;
}

export interface ShoppingOffer {
  title: string;
  mallName: string;
  priceKRW: number;
  imageUrl: string;
  link: string;
}

export interface ProductOffers {
  configured: boolean;
  offers: ShoppingOffer[];
}

export interface YoutubeSearchResult {
  configured: boolean;
  videos: YoutubeVideo[];
}

export interface AuthUser {
  id: string;
  email: string | null;
}

export interface MeResponse {
  user: AuthUser;
}

export interface ApiErrorBody {
  error: string;
  code?: string;
}
