/** Domain types shared by the app (client) and API routes (server). */

export type ProductCategory = 'lip' | 'cheek' | 'eye' | 'base' | 'skincare' | 'suncare';

export type MakeupZone = 'lip' | 'blush' | 'eyeshadow' | 'eyeliner' | 'mascara' | 'highlighter' | 'contour' | 'brow' | 'foundation';

export type Texture = 'matte' | 'velvet' | 'glossy' | 'satin' | 'sheer' | 'cream' | 'shimmer';
/** Lid paint chips only. Catalog Texture stays the 7 product names. */
export type ShadowFinish = 'matte' | 'shimmer' | 'glitter' | 'glossy';

/** How a shade color was obtained (AR_SPEC 1-8). Measured values always win over estimates. */
export type MeasureMethod = 'measured' | 'user_verified' | 'estimated' | 'placeholder';

/** CIE Lab, D65. */
export interface LabColor {
  L: number;
  a: number;
  b: number;
}

/** Cosmetic care filters for `GET /api/products?concerns=`. Never a medical diagnosis. */
export type SkinConcern =
  | 'dryness'
  | 'oiliness'
  | 'sensitivity'
  | 'blemish'
  | 'pores'
  | 'pigmentation'
  | 'wrinkles';

export interface ProductQuery {
  q?: string;
  category?: ProductCategory;
  concerns?: SkinConcern[];
}

export interface Shade {
  id: string;
  name: string;
  hex: string;
  measureMethod?: MeasureMethod;
  /** Where an estimated color came from (AR_SPEC 6-15-2). */
  colorSource?: 'measured' | 'option_chip' | 'color_compare' | 'product_photo' | 'official_hex' | 'placeholder';
  labEstimated?: LabColor;
  /** 0..1 confidence of the color extraction, when the source reports one. */
  colorConfidence?: number;
  colorCheckedAt?: string;
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
  /** How `texture` was decided (AR_SPEC 6-15-2). */
  textureSource?: 'measured' | 'team_panel' | 'name_keyword' | 'official_description' | 'review_summary' | 'review_survey' | 'default';
  /** Page the product data was checked on, and when (YYYY-MM-DD). */
  sourceUrl?: string;
  checkedAt?: string;
}

export interface LookItem {
  productId: string;
  shadeId?: string;
  step: 'prep' | 'base' | 'eyes' | 'cheeks' | 'lips';
}

export type HighlightArea = 'forehead' | 'nose_bridge' | 'under_eye' | 'chin';

/** Where the blush sits: on the cheekbone apple, closer to the eye, or out toward the ear. */
export type BlushPlacement = 'apple' | 'under_eye' | 'side';

/** A small round accent on the lid's inner corner (the "눈앞머리" pearl). */
export interface InnerPoint {
  hex: string;
  /** Coverage 0..1. */
  a1: number;
  /** Radius as a share of the eye width. */
  radius: number;
}

/**
 * Shape of a zone (AR_SPEC 5 RecipeStep.geometry). Unset fields use the app's defaults.
 * Eyeliner: length = wing length and thickness = line thickness at the outer corner, both as a share of
 * the eye width, angle = wing angle above the eye axis in degrees (negative = puppy, below the axis),
 * linerStyle = classic_winged | puppy | tightline (omitted: inferred from angle/length).
 * linerSoftness 0 (crisp) .. 1 (smudged), linerLower = also draw the lower lid line, linerLowerThickness = its
 * thickness as a share of the eye width (default 0.03). All optional; unset keeps the look as it was.
 * Mascara: length = lash length and thickness = lash density, both as a multiple of the default (1);
 * lower = false leaves the lower lashes out.
 * Lip: overlip = outer line pushed out by this share of the mouth width (0..0.06, the Cupid's-bow peaks by
 * peakOverdraw more, 0..0.05; both shrink as the mouth opens), centerHighlight = brightness added at the
 * centre of the lips (0..0.3, color kept).
 * Eyeshadow: innerPoint = pearl accent at the inner corner, pearl = brightness added at the middle of the lid
 * (0..0.5, it moves with the head, color kept), shadowFinish = matte | shimmer | glitter | glossy (lid chips).
 * sparkle 0 still means matte (no particles) for older looks. glitter bool is unused.
 * Blush: blushPlacement, blushSize (multiple of the default size) and blushSoftness (0 hard edge .. 1 very soft)
 * make the cheek ellipse follow the face points instead of the default shape.
 * Highlighter: areas = only these regions (default: the standard set), intensity = multiple of its strength.
 */
export type EyelinerStyle = 'classic_winged' | 'puppy' | 'tightline';

export interface ZoneGeometry {
  length?: number;
  angle?: number;
  thickness?: number;
  linerStyle?: EyelinerStyle;
  linerSoftness?: number;
  linerLower?: boolean;
  linerLowerThickness?: number;
  upperLine?: boolean;
  underline?: boolean;
  underlineThickness?: number;
  underlineAlpha?: number;
  underlineStart?: number;
  underlineLength?: number;
  underlineJoin?: boolean;
  lower?: boolean;
  overlip?: number;
  peakOverdraw?: number;
  centerHighlight?: number;
  innerPoint?: InnerPoint;
  areas?: HighlightArea[];
  pearl?: number;
  sparkle?: number;
  glitter?: boolean;
  shadowFinish?: ShadowFinish;
  blushPlacement?: BlushPlacement;
  blushSize?: number;
  blushSoftness?: number;
  intensity?: number;
}

/** Zones that share one color: change a product in one and the others follow (when `followOnChange`). */
export interface ColorLink {
  zones: MakeupZone[];
  hex: string;
  followOnChange: boolean;
}

export interface ZoneSetting {
  hex: string;
  /** Second color of a two-tone eyeshadow: fades in at the outer corner and along the lower lash line. */
  hexTo?: string;
  /** 0..1 */
  intensity: number;
  texture: Texture;
  geometry?: ZoneGeometry;
}

/** Zones added after the first three are optional, so looks saved without them still load. */
export interface MakeupState {
  lip: ZoneSetting | null;
  blush: ZoneSetting | null;
  eyeshadow: ZoneSetting | null;
  eyeliner?: ZoneSetting | null;
  mascara?: ZoneSetting | null;
  highlighter?: ZoneSetting | null;
  contour?: ZoneSetting | null;
  brow?: ZoneSetting | null;
  foundation?: ZoneSetting | null;
}

export interface VideoProductMapping {
  mappingVerified?: boolean;
  catalogProductId?: string;
  catalogShadeId?: string;
}

export interface CelebrityVideoProduct extends VideoProductMapping {
  number: number;
  category: string;
  zone: string;
  brand: string;
  name: string;
  option: string;
  reviewStatus: string;
  sourceType: string;
}

export interface CelebrityVideo {
  id: string;
  celebrityId: string;
  number: number;
  startSeconds: number;
  linkStatus: 'metadata_available' | 'needs_review';
  title: string;
  channelName: string;
  products: CelebrityVideoProduct[];
}

export interface StyleLookProduct extends VideoProductMapping {
  number: number;
  brand: string;
  name: string;
  option: string;
  category: string;
  zone: string;
  reviewStatus: string;
}

export interface StyleLook {
  id: string;
  title: string;
  group: string;
  tag: string;
  videoUrl: string;
  products: StyleLookProduct[];
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
  colorLinks?: ColorLink[];
  /** The look's key zones, shown first and marked in the AR panel (all other zones stay as the look sets them). */
  heroZones?: MakeupZone[];
  /** The order the look is put on (how-to pictures and the camera guide); zones left out follow in the default order. */
  stepOrder?: MakeupZone[];
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

export type SimilarReason = 'close_color' | 'same_texture' | 'same_category';

export interface SimilarShadeMatch {
  productId: string;
  shadeId: string;
  /** CIEDE2000 distance between official shade colors. */
  deltaE: number;
  reasons: SimilarReason[];
}

/** `GET /api/shades/similar`: ranked by official colors, not by the AR camera image. */
export interface SimilarShadesResponse {
  source: { productId: string; shadeId: string; hex: string; makeupZone: MakeupZone };
  matches: SimilarShadeMatch[];
  products: Product[];
}

export interface YoutubeSearchResult {
  configured: boolean;
  videos: YoutubeVideo[];
}

/** Product reference returned by the authenticated VISHUE chat service. */
export interface ChatProductRef {
  id: string;
  brand: string;
  name: string;
  category: string;
}

export interface ChatResponse {
  answer: string;
  products: ChatProductRef[];
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

export interface CreateOrderResponse {
  orderId: string;
  amount: number;
  checkoutUrl: string;
}

export interface OrderStatusResponse {
  orderId: string;
  status: 'pending' | 'paid';
}
