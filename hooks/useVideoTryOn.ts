import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'expo-router';
import { apiGet } from '@/lib/api';
import { arHref, parseId } from '@/lib/routes';
import { DEFAULT_INTENSITY, isArPaintZone, useMakeupStore } from '@/store/makeupStore';
import type { CelebLook, LookItem, MakeupState, MakeupZone, Product, VideoProductMapping } from '@/types';

const STEPS: Partial<Record<MakeupZone, LookItem['step']>> = {
  lip: 'lips', blush: 'cheeks', eyeshadow: 'eyes', eyeliner: 'eyes', brow: 'eyes', foundation: 'base',
};

/** Only explicit product AND shade mappings are eligible; no name matching or first-shade fallback. */
export function resolveVideoProducts(items: VideoProductMapping[], products: Product[]) {
  const usedZones = new Set<MakeupZone>();
  return items.flatMap((item, index) => {
    if (item.mappingVerified !== true || !parseId(item.catalogProductId) || !parseId(item.catalogShadeId)) return [];
    const product = products.find((candidate) => candidate.id === item.catalogProductId);
    if (!product?.makeupZone || !product.texture || !isArPaintZone(product.makeupZone) || usedZones.has(product.makeupZone)) return [];
    const shade = product.shades.find((candidate) => candidate.id === item.catalogShadeId);
    if (!shade || shade.measureMethod === 'placeholder' || shade.colorSource === 'placeholder') return [];
    usedZones.add(product.makeupZone);
    return [{ index, product, shade, zone: product.makeupZone, texture: product.texture }];
  });
}

export function useVideoTryOn(items: VideoProductMapping[], id: string, title: string) {
  const router = useRouter();
  const applyLook = useMakeupStore((store) => store.applyLook);
  const endFit = useMakeupStore((store) => store.endFit);
  const ids = [...new Set(items.flatMap((item) => item.mappingVerified === true && parseId(item.catalogProductId) && parseId(item.catalogShadeId) ? [item.catalogProductId!] : []))].sort();
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
  const selected = resolveVideoProducts(items, products.data ?? []);
  const selectedIndices = new Set(selected.map((item) => item.index));
  const open = () => {
    endFit();
    if (selected.length) {
      const makeup: MakeupState = { lip: null, blush: null, eyeshadow: null };
      const lookItems: LookItem[] = [];
      for (const { product, shade, zone, texture } of selected) {
        makeup[zone] = { hex: shade.hex, intensity: DEFAULT_INTENSITY[zone], texture };
        lookItems.push({ productId: product.id, shadeId: shade.id, step: STEPS[zone]! });
      }
      const look: CelebLook = { id, title, inspiration: '', description: '', thumbnailUrl: '', tutorialQuery: '', items: lookItems, makeup, tags: [] };
      applyLook(look, selected.map((item) => item.product));
    }
    router.push(arHref({ video: true }));
  };
  return { open, selectedIndices, count: selected.length, loading: ids.length > 0 && products.isPending, error: products.isError };
}
