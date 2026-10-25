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
  description: 'Demo color for AR testing. Not a real product.',
  keyIngredients: [],
  imageUrl: '',
  searchKeyword: '',
  tags: [DEMO_TAG],
};

// PBR_DEMO_SPEC 3: five demo lip colors, offered in each of the seven textures.
const LIP_COLORS = [
  { id: 'demo-rose', name: 'Demo Rose', hex: '#C25A6E' },
  { id: 'demo-coral', name: 'Demo Coral', hex: '#E06A4E' },
  { id: 'demo-red', name: 'Demo Red', hex: '#B3202E' },
  { id: 'demo-berry', name: 'Demo Berry', hex: '#7E2A4A' },
  { id: 'demo-nude', name: 'Demo Nude', hex: '#C08A7A' },
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
  brand: `Demo ${label}`,
  name: `Demo Lip ${label}`,
  nameKo: `데모 립 ${ko} (실제 제품 아님)`,
  category: 'lip',
  makeupZone: 'lip',
  texture,
  shades: LIP_COLORS,
}));

const DEMO_FACE: Product[] = [
  {
    ...base,
    id: 'demo-blush',
    brand: 'Demo Blush',
    name: 'Demo Blush',
    nameKo: '데모 블러셔 (실제 제품 아님)',
    category: 'cheek',
    makeupZone: 'blush',
    texture: 'matte',
    shades: [
      { id: 'demo-peach', name: 'Demo Peach', hex: '#F08C7A' },
      { id: 'demo-pink', name: 'Demo Pink', hex: '#E8899A' },
      { id: 'demo-mauve-pink', name: 'Demo Mauve Pink', hex: '#C97C8C' },
    ],
  },
  {
    ...base,
    id: 'demo-shadow-shimmer',
    brand: 'Demo Shimmer',
    name: 'Demo Shadow Shimmer',
    nameKo: '데모 섀도 쉬머 (실제 제품 아님)',
    category: 'eye',
    makeupZone: 'eyeshadow',
    texture: 'shimmer',
    shades: [
      { id: 'demo-bronze', name: 'Demo Bronze', hex: '#8A5A44' },
      { id: 'demo-champagne', name: 'Demo Champagne', hex: '#C9A27E' },
    ],
  },
  {
    ...base,
    id: 'demo-shadow-matte',
    brand: 'Demo Matte',
    name: 'Demo Shadow Matte',
    nameKo: '데모 섀도 매트 (실제 제품 아님)',
    category: 'eye',
    makeupZone: 'eyeshadow',
    texture: 'matte',
    shades: [
      { id: 'demo-mauve', name: 'Demo Mauve', hex: '#8E6470' },
      { id: 'demo-brown', name: 'Demo Brown', hex: '#7A5646' },
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
  brand: `Demo ${label}`,
  name: `Demo ${label}`,
  nameKo: `데모 ${ko} (실제 제품 아님)`,
  category,
  makeupZone,
  texture,
  shades,
});

const DEMO_DETAIL: Product[] = [
  demoZone('demo-liner-pencil', 'Pencil Liner', '펜슬 아이라이너', 'eye', 'eyeliner', 'matte', [
    { id: 'demo-liner-black', name: 'Demo Black', hex: '#1A1414' },
    { id: 'demo-liner-brown', name: 'Demo Brown', hex: '#4A3026' },
  ]),
  demoZone('demo-liner-liquid', 'Liquid Liner', '리퀴드 아이라이너', 'eye', 'eyeliner', 'glossy', [
    { id: 'demo-liquid-black', name: 'Demo Jet Black', hex: '#0E0C0C' },
  ]),
  demoZone('demo-mascara', 'Mascara', '마스카라', 'eye', 'mascara', 'matte', [
    { id: 'demo-mascara-black', name: 'Demo Black', hex: '#121010' },
    { id: 'demo-mascara-brown', name: 'Demo Brown', hex: '#3A2820' },
  ]),
  demoZone('demo-highlighter', 'Highlighter', '하이라이터', 'cheek', 'highlighter', 'shimmer', [
    { id: 'demo-hl-champagne', name: 'Demo Champagne', hex: '#F2DCC4' },
    { id: 'demo-hl-pearl', name: 'Demo Pearl Pink', hex: '#F4D6D6' },
  ]),
  demoZone('demo-contour', 'Contour', '쉐딩', 'cheek', 'contour', 'matte', [
    { id: 'demo-contour-taupe', name: 'Demo Taupe', hex: '#8C6A55' },
    { id: 'demo-contour-cool', name: 'Demo Cool Brown', hex: '#7A6260' },
  ]),
];

export const DEMO_PRODUCTS: Product[] = [...DEMO_LIPS, ...DEMO_FACE, ...DEMO_DETAIL];

const DEMO_NOTE = 'Demo colors, not real products.';

export const DEMO_LOOKS: CelebLook[] = [
  {
    id: 'demo-look-stage-red',
    title: 'Stage Red Velvet (Demo)',
    inspiration: `Inspired by K-pop stage looks · ${DEMO_NOTE}`,
    description: 'A bold velvet red lip with bronze shimmer lids and a soft peach cheek.',
    thumbnailUrl: '',
    tutorialQuery: 'kpop stage red lip makeup tutorial',
    items: [
      { productId: 'demo-shadow-shimmer', shadeId: 'demo-bronze', step: 'eyes' },
      { productId: 'demo-blush', shadeId: 'demo-peach', step: 'cheeks' },
      { productId: 'demo-lip-velvet', shadeId: 'demo-red', step: 'lips' },
    ],
    makeup: {
      lip: { hex: '#B3202E', intensity: 0.85, texture: 'velvet' },
      blush: { hex: '#F08C7A', intensity: 0.35, texture: 'matte' },
      eyeshadow: { hex: '#8A5A44', intensity: 0.55, texture: 'shimmer' },
    },
    tags: [DEMO_TAG, 'bold'],
  },
  {
    id: 'demo-look-glass-rose',
    title: 'Glass Glow Rose (Demo)',
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
    tags: [DEMO_TAG, 'glow'],
  },
  {
    id: 'demo-look-soft-berry',
    title: 'Soft Berry Satin (Demo)',
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
    tags: [DEMO_TAG, 'daily'],
  },
];
