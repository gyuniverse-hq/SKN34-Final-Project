import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'expo-router';
import { apiGet } from '@/lib/api';
import { applicationProfileFor, lookApplicationProfileFor, validatedApplicationProfile } from '@/lib/applicationProfiles';
import { devCatalogProduct } from '@/lib/devCatalog';
import { demoLookProduct } from '@/lib/demoLookBundle';
import { demoLookSlots, demoLookVideoId } from '@/lib/demoLookAr';
import { falseLashClusters } from '@/lib/falseLashLooks';
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
    return [{ index, product, shade, zone: product.makeupZone, texture: product.texture, style: undefined, lashes: undefined, hexTo: undefined }];
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
    // Second shadow color: skipped (the main shade stays) when its product or shade cannot be resolved.
    let hexTo: string | undefined;
    if (slot.to) {
      const toShade = products
        .find((candidate) => candidate.id === slot.to!.productId)
        ?.shades.find((candidate) => candidate.id === slot.to!.shadeId);
      if (toShade && toShade.measureMethod !== 'placeholder' && toShade.colorSource !== 'placeholder') hexTo = toShade.hex;
    }
    usedZones.add(slot.zone);
    return [{
      index: -1, product, shade, zone: slot.zone, texture: product.texture, style: slot.style,
      lashes: slot.lashes, hexTo,
    }];
  });
}

const DEV_FETCH_TIMEOUT_MS = 8000;

export function useVideoTryOn(items: VideoProductMapping[], id: string, title: string) {
  const router = useRouter();
  const applyLook = useMakeupStore((store) => store.applyLook);
  const endFit = useMakeupStore((store) => store.endFit);
  const verifiedIds = items.flatMap((item) => item.mappingVerified === true && parseId(item.catalogProductId) ? [item.catalogProductId!] : []);
  const demoIds = demoLookSlots(id).flatMap((slot) => (slot.to ? [slot.productId, slot.to.productId] : [slot.productId]));
  // Demo look products ship in the app (lib/demoLookBundle.json): no network wait before the look paints.
  const bundled = [...new Set(demoIds)].flatMap((productId) => {
    const product = demoLookProduct(productId);
    return product ? [product] : [];
  });
  const bundledIds = new Set(bundled.map((product) => product.id));
  const ids = [...new Set([
    ...verifiedIds,
    ...demoIds.filter((productId) => !bundledIds.has(productId)),
  ])].sort();
  const products = useQuery({
    queryKey: ['video-tryon-products', ids],
    enabled: ids.length > 0,
    // Development only: a dead dev server must not hold the AR button for 90 s (30 s timeout x 3 tries).
    retry: __DEV__ ? false : undefined,
    queryFn: async () => {
      const chunks: string[][] = [];
      for (let index = 0; index < ids.length; index += 20) chunks.push(ids.slice(index, index + 20));
      let found: Product[];
      try {
        const results = await Promise.all(chunks.map((chunk) => apiGet<{ products: Product[] }>(
          `/api/products?ids=${encodeURIComponent(chunk.join(','))}`,
          __DEV__ ? { timeoutMs: DEV_FETCH_TIMEOUT_MS } : {},
        )));
        found = results.flatMap((result) => result.products);
      } catch (error) {
        // status 0 = timeout or no network. Other errors (4xx/5xx) are real answers and stay errors.
        if (!__DEV__ || (error as { status?: number } | null)?.status !== 0) throw error;
        console.warn('[video-tryon] backend unavailable, using the local catalog', error);
        found = [];
      }
      if (!__DEV__) return found;
      const have = new Set(found.map((product) => product.id));
      return found.concat(ids.flatMap((productId) => {
        const local = have.has(productId) ? undefined : devCatalogProduct(productId);
        return local ? [local] : [];
      }));
    },
  });
  const fetched = products.data ?? [];
  const fetchedIds = new Set(fetched.map((product) => product.id));
  const catalog = fetched.concat(bundled.filter((product) => !fetchedIds.has(product.id)));
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
    // The product lookup failed and nothing could be painted: stay here (the screen shows the error)
    // instead of opening an AR camera without the look.
    if (products.isError && !selected.length) return;
    endFit();
    if (selected.length) {
      const makeup: MakeupState = { ...EMPTY_MAKEUP };
      const lookItems: LookItem[] = [];
      for (const { product, shade, zone, texture, style, lashes, hexTo } of selected) {
        const base = style ? geometryFromStyle(zone, style) : null;
        const initialGeometry = zone === 'mascara' && lashes ? { ...base, falseLash: falseLashClusters(lashes) } : base;
        const lookProfile = lookApplicationProfileFor(demoLookVideoId(id), zone);
        const geometry = lookProfile?.geometry ? { ...initialGeometry, ...lookProfile.geometry } : initialGeometry;
        const mascara = zone === 'mascara' && style && style in MASCARA_LOOKS
          ? MASCARA_LOOKS[style as MascaraLookId]
          : null;
        const applicationProfile = lookProfile?.overrides ?? applicationProfileFor(product.id, shade.id) ?? validatedApplicationProfile(shade.applicationProfile);
        makeup[zone] = {
          hex: shade.hex,
          intensity: mascara?.intensity ?? DEFAULT_INTENSITY[zone],
          texture,
          ...(geometry ? { geometry } : {}),
          ...(hexTo ? { hexTo } : {}),
          ...(applicationProfile ? { applicationProfile } : {}),
        };
        lookItems.push({ productId: product.id, shadeId: shade.id, step: STEPS[zone] });
      }
      const look: CelebLook = { id, title, inspiration: '', description: '', thumbnailUrl: '', tutorialQuery: '', items: lookItems, makeup, tags: [] };
      applyLook(look, selected.map((item) => item.product));
    }
    router.push(arHref(selected.length ? { video: true } : {}));
  };
  const productsById = Object.fromEntries(catalog.map((product) => [product.id, product]));
  return {
    open, selectedIndices, productsById, count: selected.length,
    missingCore: missingCoreZones(selected.map((item) => item.zone)),
    // A demo look paints from the bundle at once; the network only adds verified video mappings.
    loading: ids.length > 0 && products.isPending && bundled.length === 0, error: products.isError && bundled.length === 0,
  };
}
