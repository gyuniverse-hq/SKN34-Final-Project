import { demoLookSlots } from '@/lib/demoLookAr';
import { videoLookMakeup } from '@/lib/videoLookMakeup';
import type { CelebLook, MakeupZone, Product, Shade } from '@/types';

export type LookPreviewProduct = { product: Product; shade: Shade };

export type LookPreviewZone = {
  zone: MakeupZone;
  index: number;
  hex: string;
  hexTo?: string;
  product?: LookPreviewProduct;
  secondaryProduct?: LookPreviewProduct;
  labelKey: `ar.zone.${MakeupZone}`;
  hintKey: `lookPreview.hint.${MakeupZone}`;
};

const ZONE_ORDER: MakeupZone[] = [
  'foundation',
  'contour',
  'highlighter',
  'blush',
  'brow',
  'eyeshadow',
  'eyeliner',
  'mascara',
  'lip',
];

function isUsableHex(hex: string | undefined): hex is string {
  return typeof hex === 'string' && /^#[0-9A-Fa-f]{6}$/.test(hex);
}

function exactProduct(product: Product, shadeId: string | undefined) {
  const shade = product.shades.find((candidate) => candidate.id === shadeId);
  return shade ? { product, shade } : undefined;
}

export function buildLookPreview(look: CelebLook, products: Product[], video: boolean): LookPreviewZone[] {
  const makeup = videoLookMakeup(look.makeup, {
    fromVideo: video, cameraActive: true, fittingProduct: false, lookId: look.id, modified: [],
  });
  const productsById = new Map(products.map((product) => [product.id, product]));
  const selected = new Map<MakeupZone, LookPreviewProduct>();
  for (const item of look.items) {
    const product = productsById.get(item.productId);
    if (!product?.makeupZone) continue;
    const match = exactProduct(product, item.shadeId);
    if (match) selected.set(product.makeupZone, match);
  }
  const secondary = new Map<MakeupZone, LookPreviewProduct>();
  if (video) {
    for (const slot of demoLookSlots(look.id)) {
      if (!slot.to || !look.makeup[slot.zone]?.hexTo) continue;
      const product = productsById.get(slot.to.productId);
      const match = product && exactProduct(product, slot.to.shadeId);
      if (match) secondary.set(slot.zone, match);
    }
  }
  const zones: LookPreviewZone[] = [];
  for (const zone of ZONE_ORDER) {
    const layer = makeup[zone] ?? (zone === 'lip' ? makeup.lipCare : null);
    if (!isUsableHex(layer?.hex)) continue;
    zones.push({
      zone, index: zones.length + 1, hex: layer.hex,
      hexTo: isUsableHex(layer.hexTo) ? layer.hexTo : undefined,
      product: selected.get(zone), secondaryProduct: secondary.get(zone),
      labelKey: `ar.zone.${zone}`, hintKey: `lookPreview.hint.${zone}`,
    });
  }
  return zones;
}
