import { DEMO_TAG } from '@/constants/demo';
import type { CelebLook, Product, Texture } from '@/types';

/**
 * Demo try-on data for local development only (AR_SPEC 6-9-2 "placeholder", PBR_DEMO_SPEC 3).
 * Colors are demo values, NOT real product measurements, and prices are dummy values.
 * The AR screen uses these only in development builds when the backend has no try-on products
 * (lib/devCatalog/index.ts). Replace in M7.
 * Looks use concept names only, never a real person's name or photo (AR_SPEC 1-6).
 */
const base = {
  priceKRW: 1,
  volume: '-',
  description: 'Sample color for AR testing. Not a real product.',
  keyIngredients: [],
  imageUrl: '',
  searchKeyword: '',
  tags: [DEMO_TAG],
};

// PBR_DEMO_SPEC 3: five demo lip colors, offered in each of the seven textures.
const LIP_COLORS = [
  { id: 'demo-rose', name: 'Rose', hex: '#C25A6E' },
  { id: 'demo-coral', name: 'Coral', hex: '#E06A4E' },
  { id: 'demo-red', name: 'Red', hex: '#B3202E' },
  { id: 'demo-berry', name: 'Berry', hex: '#7E2A4A' },
  { id: 'demo-nude', name: 'Nude', hex: '#C08A7A' },
];
const LIP_TEXTURES: { texture: Texture; label: string; ko: string }[] = [
  { texture: 'matte', label: 'Matte', ko: '매트' },
  { texture: 'velvet', label: 'Velvet', ko: '벨벳' },
  { texture: 'cream', label: 'Cream', ko: '크림' },
  { texture: 'satin', label: 'Satin', ko: '새틴' },
  { texture: 'sheer', label: 'Sheer', ko: '시어' },
  { texture: 'glossy', label: 'Glossy', ko: '글로시' },
  { texture: 'shimmer', label: 'Shimmer', ko: '쉬머' },
];

const DEMO_LIPS: Product[] = LIP_TEXTURES.map(({ texture, label, ko }) => ({
  ...base,
  id: `demo-lip-${texture}`,
  brand: 'Sample',
  name: `Lip ${label}`,
  nameKo: `예시 립 ${ko} (실제 제품 아님)`,
  category: 'lip',
  makeupZone: 'lip',
  texture,
  shades: LIP_COLORS,
}));

const DEMO_FACE: Product[] = [
  {
    ...base,
    id: 'demo-blush',
    brand: 'Sample',
    name: 'Blush',
    nameKo: '예시 블러셔 (실제 제품 아님)',
    category: 'cheek',
    makeupZone: 'blush',
    texture: 'matte',
    shades: [
      { id: 'demo-peach', name: 'Peach', hex: '#F08C7A' },
      { id: 'demo-pink', name: 'Pink', hex: '#E8899A' },
      { id: 'demo-mauve-pink', name: 'Mauve Pink', hex: '#C97C8C' },
    ],
  },
  {
    ...base,
    id: 'demo-shadow-shimmer',
    brand: 'Sample',
    name: 'Shadow Shimmer',
    nameKo: '예시 섀도 쉬머 (실제 제품 아님)',
    category: 'eye',
    makeupZone: 'eyeshadow',
    texture: 'shimmer',
    shades: [
      { id: 'demo-bronze', name: 'Bronze', hex: '#8A5A44' },
      { id: 'demo-champagne', name: 'Champagne', hex: '#C9A27E' },
    ],
  },
  {
    ...base,
    id: 'demo-shadow-matte',
    brand: 'Sample',
    name: 'Shadow Matte',
    nameKo: '예시 섀도 매트 (실제 제품 아님)',
    category: 'eye',
    makeupZone: 'eyeshadow',
    texture: 'matte',
    shades: [
      { id: 'demo-mauve', name: 'Mauve', hex: '#8E6470' },
      { id: 'demo-brown', name: 'Brown', hex: '#7A5646' },
    ],
  },
];

// Liner, mascara, highlighter and contour (10-25): demo colors to test the new zones.
const demoZone = (
  id: string,
  label: string,
  ko: string,
  category: Product['category'],
  makeupZone: Product['makeupZone'],
  texture: Texture,
  shades: { id: string; name: string; hex: string }[]
): Product => ({
  ...base,
  id,
  brand: 'Sample',
  name: label,
  nameKo: `예시 ${ko} (실제 제품 아님)`,
  category,
  makeupZone,
  texture,
  shades,
});

const DEMO_DETAIL: Product[] = [
  demoZone('demo-liner-pencil', 'Pencil Liner', '펜슬 아이라이너', 'eye', 'eyeliner', 'matte', [
    { id: 'demo-liner-black', name: 'Black', hex: '#1A1414' },
    { id: 'demo-liner-brown', name: 'Brown', hex: '#4A3026' },
    { id: 'demo-liner-soft-brown', name: 'Soft Brown', hex: '#6B4A3A' },
  ]),
  demoZone('demo-liner-liquid', 'Liquid Liner', '리퀴드 아이라이너', 'eye', 'eyeliner', 'glossy', [
    { id: 'demo-liquid-black', name: 'Jet Black', hex: '#0E0C0C' },
  ]),
  demoZone('demo-mascara', 'Mascara', '마스카라', 'eye', 'mascara', 'matte', [
    { id: 'demo-mascara-black', name: 'Black', hex: '#121010' },
    { id: 'demo-mascara-brown', name: 'Brown', hex: '#3A2820' },
    { id: 'demo-mascara-jet', name: 'Jet Black', hex: '#0E0B0B' },
    { id: 'demo-mascara-soft', name: 'Soft Black', hex: '#2A1E1A' },
  ]),
  demoZone('demo-highlighter', 'Highlighter', '하이라이터', 'cheek', 'highlighter', 'shimmer', [
    { id: 'demo-hl-champagne', name: 'Champagne', hex: '#F2DCC4' },
    { id: 'demo-hl-pearl', name: 'Pearl Pink', hex: '#F4D6D6' },
  ]),
  demoZone('demo-contour', 'Contour', '쉐딩', 'cheek', 'contour', 'matte', [
    { id: 'demo-contour-taupe', name: 'Taupe', hex: '#8C6A55' },
    { id: 'demo-contour-cool', name: 'Cool Brown', hex: '#7A6260' },
    { id: 'demo-contour-warm', name: 'Warm Brown', hex: '#8A5A44' },
  ]),
  demoZone('demo-brow', 'Brow', '아이브로우', 'eye', 'brow', 'matte', [
    { id: 'demo-brow-dark-brown', name: 'Dark Brown', hex: '#3D2918' },
    { id: 'demo-brow-choco', name: 'Choco Brown', hex: '#6B4428' },
    { id: 'demo-brow-natural', name: 'Natural Brown', hex: '#7A5340' },
    { id: 'demo-brow-light', name: 'Light Brown', hex: '#A67C52' },
    { id: 'demo-brow-ash', name: 'Ash Brown', hex: '#8A7B72' },
  ]),
  demoZone('demo-foundation-matte', 'Foundation Matte', '파운데이션 매트', 'base', 'foundation', 'matte', [
    { id: 'demo-found-ivory', name: 'Ivory', hex: '#F3E0D0' },
    { id: 'demo-found-beige', name: 'Beige', hex: '#E6C7A8' },
    { id: 'demo-found-sand', name: 'Sand', hex: '#D2A679' },
    { id: 'demo-found-tan', name: 'Tan', hex: '#A8754F' },
  ]),
  demoZone('demo-foundation-sheer', 'Foundation Sheer', '파운데이션 시어', 'base', 'foundation', 'sheer', [
    { id: 'demo-found-sheer-ivory', name: 'Ivory', hex: '#F3E0D0' },
    { id: 'demo-found-sheer-beige', name: 'Beige', hex: '#E6C7A8' },
    { id: 'demo-found-sheer-sand', name: 'Sand', hex: '#D2A679' },
    { id: 'demo-found-sheer-tan', name: 'Tan', hex: '#A8754F' },
  ]),
];

// Gal look (10-26): a pale nude matte lip and a white pearl shadow whose second tone (brown) comes from the
// look itself (`hexTo`), so the shade here is only the pearl.
const DEMO_GAL: Product[] = [
  demoZone('demo-lip-gal', 'Gal Nude Matte', '갸루 누드 매트 립', 'lip', 'lip', 'matte', [
    { id: 'demo-gal-nude', name: 'Nude Beige', hex: '#D2A593' },
  ]),
  demoZone('demo-shadow-gal', 'Gal Pearl Shadow', '갸루 펄 섀도 (펄 화이트 + 브라운)', 'eye', 'eyeshadow', 'shimmer', [
    { id: 'demo-gal-pearl', name: 'White Pearl', hex: '#F3E9DF' },
  ]),
];

// Retro & semi gal look (10-26): lip, shadow, highlighter and contour shades the look names.
const DEMO_SEMI: Product[] = [
  demoZone('demo-lip-semi', 'Semi Gal Cream', '세미 갸루 크림 립', 'lip', 'lip', 'cream', [
    { id: 'demo-semi-nude', name: 'Dusty Nude', hex: '#C99A8A' },
  ]),
  demoZone('demo-shadow-semi', 'Semi Gal Shimmer', '세미 갸루 쉬머 섀도', 'eye', 'eyeshadow', 'shimmer', [
    { id: 'demo-semi-champagne', name: 'Champagne Beige', hex: '#E9D2C2' },
  ]),
  demoZone('demo-highlighter-satin', 'Satin Highlighter', '새틴 하이라이터', 'cheek', 'highlighter', 'satin', [
    { id: 'demo-hl-ivory', name: 'Ivory', hex: '#FFF4EC' },
    { id: 'demo-hl-peach-ivory', name: 'Peach Ivory', hex: '#FFF1E6' },
  ]),
];

// Soft peach coral look (10-26): blush and shadow share one peach coral, the lip is a sheer coral tint.
const DEMO_PEACH: Product[] = [
  demoZone('demo-blush-sheer', 'Sheer Blush', '시어 블러셔', 'cheek', 'blush', 'sheer', [
    { id: 'demo-peach-coral-cheek', name: 'Peach Coral', hex: '#F4A78A' },
  ]),
  demoZone('demo-shadow-peach', 'Peach Shimmer', '피치 쉬머 섀도', 'eye', 'eyeshadow', 'shimmer', [
    { id: 'demo-peach-coral-lid', name: 'Peach Coral', hex: '#F4A78A' },
  ]),
  demoZone('demo-lip-coral', 'Coral Tint', '코랄 틴트', 'lip', 'lip', 'sheer', [
    { id: 'demo-coral-tint', name: 'Coral Tint', hex: '#F2735B' },
  ]),
];

// Snake-eye idol look (10-26): taken from an idol cover tutorial's product list and finished face (AR_SPEC 6-5-8).
const DEMO_IDOL: Product[] = [
  demoZone('demo-blush-cool-pink', 'Cool Pink Powder Blush', '쿨 핑크 파우더 블러셔', 'cheek', 'blush', 'matte', [
    { id: 'demo-cool-pink', name: 'Cool Pink', hex: '#EC9DB0' },
  ]),
  demoZone('demo-shadow-mauve-taupe', 'Mauve Taupe Shadow', '모브 토프 섀도', 'eye', 'eyeshadow', 'matte', [
    { id: 'demo-mauve-taupe', name: 'Mauve Taupe', hex: '#B08A8C' },
  ]),
  demoZone('demo-lip-cherry-glow', 'Cherry Glow Tint', '체리 글로우 틴트', 'lip', 'lip', 'glossy', [
    { id: 'demo-cherry-rose', name: 'Cherry Rose', hex: '#C9566A' },
  ]),
  demoZone('demo-highlighter-rose-gold', 'Rose Gold Glow', '로즈 골드 하이라이터', 'cheek', 'highlighter', 'shimmer', [
    { id: 'demo-hl-rose-gold', name: 'Rose Gold', hex: '#F6D9CF' },
  ]),
];

/** One lip on the shop in development, so the product-page AR path can be tapped. */
export const DEMO_SHOP_LIP: Product = {
  ...base,
  id: 'demo-lip-tryon',
  brand: 'Sample',
  name: 'AR Try-On Lip',
  nameKo: 'AR 확인용 립 (실제 제품 아님)',
  category: 'lip',
  makeupZone: 'lip',
  texture: 'glossy',
  priceKRW: 18000,
  volume: '3g',
  description: 'One demo lip for checking AR from the product page. Not a real product.',
  searchKeyword: 'AR try on lip',
  shades: [{ id: 'demo-tryon-red', name: 'Try-On Red', hex: '#B3202E', measureMethod: 'placeholder' }],
};

export const DEMO_PRODUCTS: Product[] = [
  ...DEMO_LIPS,
  ...DEMO_FACE,
  ...DEMO_DETAIL,
  ...DEMO_GAL,
  ...DEMO_SEMI,
  ...DEMO_PEACH,
  ...DEMO_IDOL,
  DEMO_SHOP_LIP,
];

const DEMO_NOTE = 'Sample colors, not real products.';

export const DEMO_LOOKS: CelebLook[] = [
  {
    id: 'demo-look-stage-red',
    title: 'Stage Red Velvet',
    inspiration: `Inspired by K-pop stage looks · ${DEMO_NOTE}`,
    description:
      'A full stage look: bronze shimmer lids smoked darker at the outer corner, a sharp black wing, full lashes, a warm peach flush, a soft glow on the nose bridge and under the eyes, light contour and a bold velvet red lip.',
    thumbnailUrl: '',
    tutorialQuery: 'kpop stage red lip makeup tutorial',
    items: [
      { productId: 'demo-shadow-shimmer', shadeId: 'demo-bronze', step: 'eyes' },
      { productId: 'demo-liner-liquid', shadeId: 'demo-liquid-black', step: 'eyes' },
      { productId: 'demo-mascara', shadeId: 'demo-mascara-black', step: 'eyes' },
      { productId: 'demo-blush', shadeId: 'demo-peach', step: 'cheeks' },
      { productId: 'demo-contour', shadeId: 'demo-contour-warm', step: 'cheeks' },
      { productId: 'demo-highlighter', shadeId: 'demo-hl-champagne', step: 'cheeks' },
      { productId: 'demo-lip-velvet', shadeId: 'demo-red', step: 'lips' },
    ],
    makeup: {
      lip: { hex: '#B3202E', intensity: 0.85, texture: 'velvet' },
      blush: { hex: '#F08C7A', intensity: 0.5, texture: 'matte' },
      eyeshadow: { hex: '#8A5A44', hexTo: '#3E271E', intensity: 0.7, texture: 'shimmer' },
      eyeliner: { hex: '#0E0C0C', intensity: 1, texture: 'glossy', geometry: { length: 0.3, angle: 15, thickness: 0.06 } },
      mascara: { hex: '#121010', intensity: 0.9, texture: 'matte', geometry: { length: 1.3, thickness: 1.3, lower: false } },
      highlighter: { hex: '#F2DCC4', intensity: 0.7, texture: 'shimmer', geometry: { areas: ['nose_bridge', 'under_eye'] } },
      contour: { hex: '#8A5A44', intensity: 0.5, texture: 'matte' },
    },
    // Lip, shadow and blush carry the look; the liner, lashes, glow and contour only support them.
    heroZones: ['lip', 'eyeshadow', 'blush'],
    // Stage: sculpt the face first, then the eyes, then the bold lip last.
    stepOrder: ['contour', 'highlighter', 'eyeshadow', 'eyeliner', 'mascara', 'blush', 'lip'],
    tags: [DEMO_TAG, 'bold'],
  },
  {
    id: 'demo-look-glass-rose',
    title: 'Glass Glow Rose',
    inspiration: `Inspired by K-drama glow makeup · ${DEMO_NOTE}`,
    description: 'A glossy rose lip, champagne shimmer lids and a pink flush.',
    thumbnailUrl: '',
    tutorialQuery: 'korean glass skin glossy lip makeup tutorial',
    items: [
      { productId: 'demo-shadow-shimmer', shadeId: 'demo-champagne', step: 'eyes' },
      { productId: 'demo-blush', shadeId: 'demo-pink', step: 'cheeks' },
      { productId: 'demo-lip-glossy', shadeId: 'demo-rose', step: 'lips' },
    ],
    makeup: {
      lip: { hex: '#C25A6E', intensity: 0.7, texture: 'glossy' },
      blush: { hex: '#E8899A', intensity: 0.45, texture: 'matte' },
      eyeshadow: { hex: '#C9A27E', intensity: 0.45, texture: 'shimmer' },
    },
    // Glow: flush the cheeks first and keep the lids light.
    stepOrder: ['blush', 'eyeshadow', 'lip'],
    tags: [DEMO_TAG, 'glow'],
  },
  {
    id: 'demo-look-soft-berry',
    title: 'Soft Berry Satin',
    inspiration: `Inspired by K-pop idol daily looks · ${DEMO_NOTE}`,
    description: 'A satin berry lip with matte mauve lids and a muted mauve-pink cheek.',
    thumbnailUrl: '',
    tutorialQuery: 'kpop idol berry lip daily makeup tutorial',
    items: [
      { productId: 'demo-shadow-matte', shadeId: 'demo-mauve', step: 'eyes' },
      { productId: 'demo-blush', shadeId: 'demo-mauve-pink', step: 'cheeks' },
      { productId: 'demo-lip-satin', shadeId: 'demo-berry', step: 'lips' },
    ],
    makeup: {
      lip: { hex: '#7E2A4A', intensity: 0.75, texture: 'satin' },
      blush: { hex: '#C97C8C', intensity: 0.35, texture: 'matte' },
      eyeshadow: { hex: '#8E6470', intensity: 0.5, texture: 'matte' },
    },
    // Daily: lids, then the lip, and a touch of cheek to tie them together.
    stepOrder: ['eyeshadow', 'lip', 'blush'],
    tags: [DEMO_TAG, 'daily'],
  },
  {
    id: 'demo-look-gal-classic',
    title: 'Gal Classic',
    inspiration: `Inspired by Japanese gyaru makeup · ${DEMO_NOTE}`,
    description:
      'A pale nude matte lip, white pearl lids shaded brown at the outer corner and lower lash line, a long thick wing liner, dense lashes and a bright nose bridge.',
    thumbnailUrl: '',
    tutorialQuery: 'gyaru gal makeup tutorial',
    items: [
      { productId: 'demo-shadow-gal', shadeId: 'demo-gal-pearl', step: 'eyes' },
      { productId: 'demo-liner-liquid', shadeId: 'demo-liquid-black', step: 'eyes' },
      { productId: 'demo-mascara', shadeId: 'demo-mascara-black', step: 'eyes' },
      { productId: 'demo-highlighter', shadeId: 'demo-hl-pearl', step: 'cheeks' },
      { productId: 'demo-lip-gal', shadeId: 'demo-gal-nude', step: 'lips' },
    ],
    makeup: {
      lip: { hex: '#D2A593', intensity: 0.8, texture: 'matte' },
      blush: null,
      eyeshadow: { hex: '#F3E9DF', hexTo: '#5A3A2C', intensity: 0.85, texture: 'shimmer' },
      eyeliner: { hex: '#0E0C0C', intensity: 1, texture: 'glossy', geometry: { length: 0.42, angle: 12, thickness: 0.075 } },
      mascara: { hex: '#121010', intensity: 1, texture: 'matte', geometry: { length: 1.55, thickness: 1.6 } },
      highlighter: { hex: '#F4D6D6', intensity: 0.8, texture: 'shimmer' },
    },
    // Gal: the eyes are the whole look, so they come first and get the most time.
    stepOrder: ['eyeshadow', 'eyeliner', 'mascara', 'highlighter', 'lip'],
    tags: [DEMO_TAG, 'gal'],
  },
  {
    id: 'demo-look-semi-gyaru-retro',
    title: 'Retro & Semi Gal',
    inspiration: `Inspired by Y2K gyaru makeup · ${DEMO_NOTE}`,
    description:
      'A dusty nude cream lip drawn slightly over the lip line, champagne lids with a white pearl at the inner corner fading to brown, a long wing liner, full lashes, bright forehead, nose bridge and under-eyes, and soft contour.',
    thumbnailUrl: '',
    tutorialQuery: 'semi gyaru y2k retro makeup tutorial',
    // Plan values (a1 = how much is covered) map to the app's intensity: contour 0.35 → 0.6, highlighter 0.45 → 0.9,
    // shadow 0.4 → 0.5, liner 0.9 → 0.9, mascara 0.85 → 0.78, cream lip 0.7 → 0.46.
    items: [
      { productId: 'demo-contour', shadeId: 'demo-contour-warm', step: 'cheeks' },
      { productId: 'demo-highlighter-satin', shadeId: 'demo-hl-ivory', step: 'cheeks' },
      { productId: 'demo-shadow-semi', shadeId: 'demo-semi-champagne', step: 'eyes' },
      { productId: 'demo-liner-pencil', shadeId: 'demo-liner-black', step: 'eyes' },
      { productId: 'demo-mascara', shadeId: 'demo-mascara-jet', step: 'eyes' },
      { productId: 'demo-lip-semi', shadeId: 'demo-semi-nude', step: 'lips' },
    ],
    makeup: {
      lip: { hex: '#C99A8A', intensity: 0.46, texture: 'cream', geometry: { overlip: 0.03, peakOverdraw: 0.02, centerHighlight: 0.15 } },
      blush: null,
      eyeshadow: {
        hex: '#E9D2C2',
        hexTo: '#6B4A3A',
        intensity: 0.5,
        texture: 'shimmer',
        geometry: { innerPoint: { hex: '#FFFFFF', a1: 0.6, radius: 0.18 } },
      },
      eyeliner: { hex: '#1A1414', intensity: 0.9, texture: 'matte', geometry: { length: 0.35, angle: 12, thickness: 0.072 } },
      mascara: { hex: '#0E0B0B', intensity: 0.78, texture: 'matte', geometry: { length: 1.5, thickness: 1.4, lower: true } },
      highlighter: { hex: '#FFF4EC', intensity: 0.9, texture: 'satin', geometry: { areas: ['forehead', 'nose_bridge', 'under_eye'] } },
      contour: { hex: '#8A5A44', intensity: 0.6, texture: 'matte' },
    },
    // Semi gal: contour and glow set the face, then the eyes, then the overlip.
    stepOrder: ['contour', 'highlighter', 'eyeshadow', 'eyeliner', 'mascara', 'lip'],
    tags: [DEMO_TAG, 'Y2K', 'festival', 'photoshoot', 'bold'],
  },
  {
    id: 'demo-look-soft-peach-coral',
    title: 'Soft Peach Coral',
    inspiration: `Inspired by spring and summer date makeup · ${DEMO_NOTE}`,
    description:
      'Warm peach coral on the lids and the apples of the cheeks in one tone, a faint pearl on the lids, a thin brown liner, light lashes, a gentle glow on the nose bridge and under the eyes, and a sheer coral lip tint.',
    thumbnailUrl: '',
    tutorialQuery: 'soft peach coral makeup tutorial',
    // Plan values (a1) map to the app's intensity: sheer blush 0.30 → 0.5, shimmer shadow 0.35 → 0.44, liner 0.55 → 0.1,
    // mascara 0.60 → 0.22, highlighter 0.25 → 0.7 (× geometry.intensity 0.6), sheer lip 0.55 → 0.56.
    items: [
      { productId: 'demo-blush-sheer', shadeId: 'demo-peach-coral-cheek', step: 'cheeks' },
      { productId: 'demo-shadow-peach', shadeId: 'demo-peach-coral-lid', step: 'eyes' },
      { productId: 'demo-liner-pencil', shadeId: 'demo-liner-soft-brown', step: 'eyes' },
      { productId: 'demo-mascara', shadeId: 'demo-mascara-soft', step: 'eyes' },
      { productId: 'demo-highlighter-satin', shadeId: 'demo-hl-peach-ivory', step: 'cheeks' },
      { productId: 'demo-lip-coral', shadeId: 'demo-coral-tint', step: 'lips' },
    ],
    makeup: {
      lip: { hex: '#F2735B', intensity: 0.56, texture: 'sheer' },
      blush: {
        hex: '#F4A78A',
        intensity: 0.5,
        texture: 'sheer',
        geometry: { blushPlacement: 'apple', blushSize: 1.1, blushSoftness: 0.85 },
      },
      eyeshadow: { hex: '#F4A78A', hexTo: '#E38B6F', intensity: 0.44, texture: 'shimmer', geometry: { pearl: 0.2, sparkle: 0 } },
      eyeliner: { hex: '#6B4A3A', intensity: 0.1, texture: 'matte', geometry: { length: 0.08, angle: 5, thickness: 0.036, linerStyle: 'tightline' } },
      mascara: { hex: '#2A1E1A', intensity: 0.22, texture: 'matte', geometry: { length: 1.1, thickness: 1, lower: false } },
      highlighter: {
        hex: '#FFF1E6',
        intensity: 0.7,
        texture: 'satin',
        geometry: { areas: ['nose_bridge', 'under_eye'], intensity: 0.6 },
      },
    },
    // Lid and cheek share one peach coral: swapping the shadow or the blush product moves the other with it.
    colorLinks: [{ zones: ['eyeshadow', 'blush'], hex: '#F4A78A', followOnChange: true }],
    // Peach: the cheek color comes first and the lids follow it, so both stay one tone.
    stepOrder: ['blush', 'eyeshadow', 'eyeliner', 'mascara', 'highlighter', 'lip'],
    tags: [DEMO_TAG, 'spring', 'summer', 'date', 'selfie', 'natural'],
  },
  {
    id: 'demo-look-snake-eye-idol',
    title: 'Sharp Snake-Eye Idol',
    inspiration: `Inspired by K-pop idol stage makeup · ${DEMO_NOTE}`,
    description:
      'A porcelain base with a wide cool-pink flush right under the eyes, mauve-taupe lids smudged dark along the outer corner and lower lash line, a long upturned black wing, lower lashes, a rose-gold glow on the forehead and nose bridge, soft cool contour and a glassy cherry-rose lip.',
    thumbnailUrl: '',
    tutorialQuery: 'kpop idol snake eye semi smoky makeup tutorial',
    items: [
      { productId: 'demo-contour', shadeId: 'demo-contour-cool', step: 'cheeks' },
      { productId: 'demo-highlighter-rose-gold', shadeId: 'demo-hl-rose-gold', step: 'cheeks' },
      { productId: 'demo-blush-cool-pink', shadeId: 'demo-cool-pink', step: 'cheeks' },
      { productId: 'demo-shadow-mauve-taupe', shadeId: 'demo-mauve-taupe', step: 'eyes' },
      { productId: 'demo-liner-liquid', shadeId: 'demo-liquid-black', step: 'eyes' },
      { productId: 'demo-mascara', shadeId: 'demo-mascara-black', step: 'eyes' },
      { productId: 'demo-lip-cherry-glow', shadeId: 'demo-cherry-rose', step: 'lips' },
    ],
    makeup: {
      lip: { hex: '#C9566A', intensity: 0.62, texture: 'glossy' },
      blush: {
        hex: '#EC9DB0',
        intensity: 0.85,
        texture: 'matte',
        geometry: { blushPlacement: 'under_eye', blushSize: 1.4, blushSoftness: 0.9 },
      },
      // Semi-smoky: the dark second tone sits at the outer corner and along the lower lash line.
      eyeshadow: { hex: '#B08A8C', hexTo: '#4E3B3D', intensity: 0.55, texture: 'matte' },
      eyeliner: { hex: '#0E0C0C', intensity: 1, texture: 'glossy', geometry: { length: 0.38, angle: 18, thickness: 0.05 } },
      mascara: { hex: '#121010', intensity: 0.85, texture: 'matte', geometry: { length: 1.45, thickness: 1.3, lower: true } },
      highlighter: { hex: '#F6D9CF', intensity: 0.75, texture: 'shimmer', geometry: { areas: ['forehead', 'nose_bridge'] } },
      contour: { hex: '#7A6260', intensity: 0.35, texture: 'matte' },
    },
    // Snake eye (the tutorial's order): eyes, then the flush, contour and glow, lip last.
    stepOrder: ['eyeshadow', 'eyeliner', 'mascara', 'blush', 'contour', 'highlighter', 'lip'],
    tags: [DEMO_TAG, 'idol', 'stage', 'bold'],
  },
];
