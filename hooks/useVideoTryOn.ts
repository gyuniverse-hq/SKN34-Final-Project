import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'expo-router';
import { apiGet } from '@/lib/api';
import { demoLookSlots } from '@/lib/demoLookAr';
import { MASCARA_LOOKS, type MascaraLookId } from '@/lib/mascaraLooks';
import { arHref, parseId } from '@/lib/routes';
import { geometryFromStyle } from '@/lib/zoneRecipe';
import { missingCoreZones } from '@/lib/lookProductMatch';
import { DEFAULT_INTENSITY, isLookPaintZone, useMakeupStore } from '@/store/makeupStore';
import type { CelebLook, LookItem, MakeupState, MakeupZone, Product, VideoProductMapping } from '@/types';

const STEPS: Record<MakeupZone, LookItem['step']> = {
  lip: 'lips', blush: 'cheeks', eyeshadow: 'eyes', eyeliner: 'eyes', mascara: 'eyes',
  highlighter: 'cheeks', contour: 'cheeks', brow: 'eyes', foundation: 'base',
};

const EMPTY_MAKEUP: MakeupState = {
  lip: null, blush: null, eyeshadow: null, eyeliner: null, mascara: null,
  highlighter: null, contour: null, brow: null, foundation: null,
};

/** Only explicit product AND shade mappings are eligible; no name matching or first-shade fallback. */
export function resolveVideoProducts(items: VideoProductMapping[], products: Product[]) {
  const usedZones = new Set<MakeupZone>();
  return items.flatMap((item, index) => {
    if (item.mappingVerified !== true || !parseId(item.catalogProductId) || !parseId(item.catalogShadeId)) return [];
    const product = products.find((candidate) => candidate.id === item.catalogProductId);
    if (!product?.makeupZone || !product.texture || !isLookPaintZone(product.makeupZone) || usedZones.has(product.makeupZone)) return [];
    const shade = product.shades.find((candidate) => candidate.id === item.catalogShadeId);
    if (!shade || shade.measureMethod === 'placeholder' || shade.colorSource === 'placeholder') return [];
    usedZones.add(product.makeupZone);
    return [{ index, product, shade, zone: product.makeupZone, texture: product.texture, style: undefined }];
  });
}

export function resolveDemoLookProducts(
  lookId: string,
  products: Product[],
  usedZones: Set<MakeupZone>,
) {
  return demoLookSlots(lookId).flatMap((slot) => {
    if (usedZones.has(slot.zone) || !isLookPaintZone(slot.zone)) return [];
    const product = products.find((candidate) => candidate.id === slot.productId);
    if (!product?.texture || product.makeupZone !== slot.zone) return [];
    const shade = product.shades.find((candidate) => candidate.id === slot.shadeId);
    if (!shade || shade.measureMethod === 'placeholder' || shade.colorSource === 'placeholder') return [];
    usedZones.add(slot.zone);
    return [{ index: -1, product, shade, zone: slot.zone, texture: product.texture, style: slot.style }];
  });
}

export function useVideoTryOn(items: VideoProductMapping[], id: string, title: string) {
  const router = useRouter();
  const applyLook = useMakeupStore((store) => store.applyLook);
  const endFit = useMakeupStore((store) => store.endFit);
  const ids = [...new Set([
    ...items.flatMap((item) => item.mappingVerified === true && parseId(item.catalogProductId) ? [item.catalogProductId!] : []),
    ...demoLookSlots(id).map((slot) => slot.productId),
  ])].sort();
  const products = useQuery({
    queryKey: ['video-tryon-products', ids],
    enabled: ids.length > 0,
    queryFn: async () => {
      const chunks: string[][] = [];
      for (let index = 0; index < ids.length; index += 20) chunks.push(ids.slice(index, index + 20));
      const results = await Promise.all(chunks.map((chunk) => apiGet<{ products: Product[] }>(`/api/products?ids=${encodeURIComponent(chunk.join(','))}`)));
      return results.flatMap((result) => result.products);
    },
  });
  const catalog = products.data ?? [];
  const verified = resolveVideoProducts(items, catalog);
  const selected = [
    ...verified,
    ...resolveDemoLookProducts(id, catalog, new Set(verified.map((item) => item.zone))),
  ];
  const paintedIds = new Set(selected.map((item) => item.product.id));
  const selectedIndices = new Set(items.flatMap((item, index) => (
    item.catalogProductId && paintedIds.has(item.catalogProductId) ? [index] : []
  )));
  const open = () => {
    endFit();
    if (selected.length) {
      const makeup: MakeupState = { ...EMPTY_MAKEUP };
      const lookItems: LookItem[] = [];
      for (const { product, shade, zone, texture, style } of selected) {
        const geometry = style ? geometryFromStyle(zone, style) : null;
        const mascara = zone === 'mascara' && style && style in MASCARA_LOOKS
          ? MASCARA_LOOKS[style as MascaraLookId]
          : null;
        makeup[zone] = {
          hex: shade.hex,
          intensity: mascara?.intensity ?? DEFAULT_INTENSITY[zone],
          texture,
          ...(geometry ? { geometry } : {}),
        };
        lookItems.push({ productId: product.id, shadeId: shade.id, step: STEPS[zone] });
      }
      const look: CelebLook = { id, title, inspiration: '', description: '', thumbnailUrl: '', tutorialQuery: '', items: lookItems, makeup, tags: [] };
      applyLook(look, selected.map((item) => item.product));
    }
    router.push(arHref(selected.length ? { video: true } : {}));
  };
  const productsById = Object.fromEntries((products.data ?? []).map((product) => [product.id, product]));
  return {
    open, selectedIndices, productsById, count: selected.length,
    missingCore: missingCoreZones(selected.map((item) => item.zone)),
    loading: ids.length > 0 && products.isPending, error: products.isError,
  };
}
