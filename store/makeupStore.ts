import { create } from 'zustand';
import type { CelebLook, ColorLink, MakeupState, MakeupZone, Product, Shade, ZoneGeometry, ZoneSetting } from '@/types';

export interface ZoneSelection {
  productId: string;
  shadeId: string;
}

/** Product-page try-on: this shade only, until the AR tab is left. Memory only. */
export interface ProductFit {
  productId: string;
  shadeId: string;
}

interface LookOrigin {
  makeup: MakeupState;
  selections: Partial<Record<MakeupZone, ZoneSelection>>;
}

interface FitOrigin {
  makeup: MakeupState;
  selections: Partial<Record<MakeupZone, ZoneSelection>>;
  activeLook: { id: string; title: string } | null;
  colorLinks: ColorLink[];
  heroZones: MakeupZone[];
  stepOrder: MakeupZone[];
  modified: MakeupZone[];
  lookOrigin: LookOrigin | null;
}

/** Every zone a look can name. Look recipes, look cards, and look guides keep mascara / highlighter / contour. */
export const MAKEUP_ZONES: MakeupZone[] = ['lip', 'blush', 'eyeshadow', 'eyeliner', 'mascara', 'highlighter', 'contour', 'brow', 'foundation'];

/** Zones the AR camera paints and the AR panel can pick. The three look-only zones stay in look data. */
export const AR_PAINT_ZONES: MakeupZone[] = ['lip', 'blush', 'eyeshadow', 'eyeliner', 'brow', 'foundation'];

export function isArPaintZone(zone: MakeupZone): boolean {
  return AR_PAINT_ZONES.includes(zone);
}

/** Face paint for the camera: look-only zones are stored, never drawn. */
export function arPaintMakeup(makeup: MakeupState): MakeupState {
  return { ...makeup, mascara: null, highlighter: null, contour: null };
}

export const DEFAULT_INTENSITY: Record<MakeupZone, number> = {
  lip: 0.65,
  blush: 0.45,
  eyeshadow: 0.45,
  eyeliner: 0.85,
  mascara: 0.7,
  highlighter: 0.5,
  contour: 0.4,
  brow: 0.7,
  foundation: 0.45,
};

interface MakeupStore {
  makeup: MakeupState;
  selections: Partial<Record<MakeupZone, ZoneSelection>>;
  activeLook: { id: string; title: string } | null;
  /** Links of the applied look: zones that keep one shared color while the user swaps products. */
  colorLinks: ColorLink[];
  /** Key zones of the applied look, in the order to show them. */
  heroZones: MakeupZone[];
  /** The applied look's own order of zones (empty = default order). */
  stepOrder: MakeupZone[];
  /** Zones whose color or on/off state differs from the applied look (intensity does not count). */
  modified: MakeupZone[];
  /** The applied look as it was loaded, so a zone can go back to it. */
  lookOrigin: LookOrigin | null;
  /** Shop try-on: lock to one product shade. Null in the explore tab. */
  fit: ProductFit | null;
  fitOrigin: FitOrigin | null;
  applyShade: (product: Product, shade: Shade) => void;
  applyLook: (look: CelebLook, products: Product[]) => void;
  setIntensity: (zone: MakeupZone, intensity: number) => void;
  /** Merge shape fields (liner wing, shadow gradient). Hex and texture stay. */
  patchGeometry: (zone: MakeupZone, geometry: ZoneGeometry) => void;
  clearZone: (zone: MakeupZone) => void;
  /** Put a zone (and the zones linked to it) back to the look's color and product, keeping the user's intensity. */
  revertZone: (zone: MakeupZone) => void;
  /** Paint only this product shade; snapshot the current face to restore when the AR tab is left. */
  startFit: (product: Product, shade: Shade) => void;
  endFit: () => void;
  reset: () => void;
}

/**
 * Same color and product as the look loaded (intensity and shape are the user's to move). A zone the look
 * fills with a product is the same when that product and shade are worn again; otherwise the color decides.
 */
function sameAsOrigin(
  zone: MakeupZone,
  makeup: MakeupState,
  selections: Partial<Record<MakeupZone, ZoneSelection>>,
  origin: LookOrigin
): boolean {
  const a = makeup[zone], b = origin.makeup[zone];
  if (!a || !b) return !a && !b;
  const sa = selections[zone], sb = origin.selections[zone];
  if (sb) return sa?.productId === sb.productId && sa?.shadeId === sb.shadeId;
  return !sa && a.hex === b.hex && a.texture === b.texture;
}

function modifiedZones(
  makeup: MakeupState,
  selections: Partial<Record<MakeupZone, ZoneSelection>>,
  origin: LookOrigin | null
): MakeupZone[] {
  return origin ? MAKEUP_ZONES.filter((z) => !sameAsOrigin(z, makeup, selections, origin)) : [];
}

const EMPTY: MakeupState = {
  lip: null,
  blush: null,
  eyeshadow: null,
  eyeliner: null,
  mascara: null,
  highlighter: null,
  contour: null,
  brow: null,
  foundation: null,
};

export const useMakeupStore = create<MakeupStore>((set) => ({
  makeup: EMPTY,
  selections: {},
  activeLook: null,
  colorLinks: [],
  heroZones: [],
  stepOrder: [],
  modified: [],
  lookOrigin: null,
  fit: null,
  fitOrigin: null,

  applyShade: (product, shade) => {
    const zone = product.makeupZone;
    const texture = product.texture;
    if (!zone || !texture || !isArPaintZone(zone)) return;
    set((s) => {
      if (s.fit) return s;
      // Only the color and finish change: the look's shape (wing angle, second shadow tone, ...) stays.
      const prev = s.makeup[zone];
      const next: ZoneSetting = {
        hex: shade.hex,
        texture,
        intensity: prev?.intensity ?? DEFAULT_INTENSITY[zone],
        ...(prev?.hexTo ? { hexTo: prev.hexTo } : {}),
        ...(prev?.geometry ? { geometry: prev.geometry } : {}),
      };
      const makeup: MakeupState = { ...s.makeup, [zone]: next };
      const selections = { ...s.selections, [zone]: { productId: product.id, shadeId: shade.id } };
      // A linked zone follows the new color but keeps its own finish and strength. It no longer shows a
      // product shade, so it drops out of the selection (the cart must not list a shade it is not wearing).
      for (const link of s.colorLinks) {
        if (!link.followOnChange || !link.zones.includes(zone)) continue;
        for (const other of link.zones) {
          const current = makeup[other];
          if (other === zone || !current) continue;
          makeup[other] = { ...current, hex: shade.hex };
          delete selections[other];
        }
      }
      // The look stays applied; the zones that moved off it are listed in `modified`.
      return { makeup, selections, modified: modifiedZones(makeup, selections, s.lookOrigin) };
    });
  },

  applyLook: (look, products) => {
    set((s) => {
      if (s.fit) return s;
      const selections: Partial<Record<MakeupZone, ZoneSelection>> = {};
      for (const item of look.items) {
        const product = products.find((p) => p.id === item.productId);
        if (product?.makeupZone && item.shadeId) {
          selections[product.makeupZone] = { productId: product.id, shadeId: item.shadeId };
        }
      }
      const makeup = { ...EMPTY, ...look.makeup };
      return {
        makeup,
        selections,
        activeLook: { id: look.id, title: look.title },
        colorLinks: look.colorLinks ?? [],
        heroZones: look.heroZones ?? [],
        stepOrder: look.stepOrder ?? [],
        modified: [],
        lookOrigin: { makeup, selections },
      };
    });
  },

  setIntensity: (zone, intensity) =>
    set((s) => {
      if (s.fit) return s;
      const current = s.makeup[zone];
      if (!current) return s;
      return { makeup: { ...s.makeup, [zone]: { ...current, intensity } } };
    }),

  patchGeometry: (zone, geometry) =>
    set((s) => {
      if (s.fit) return s;
      const current = s.makeup[zone];
      if (!current) return s;
      return {
        makeup: { ...s.makeup, [zone]: { ...current, geometry: { ...current.geometry, ...geometry } } },
      };
    }),

  clearZone: (zone) =>
    set((s) => {
      if (s.fit) return s;
      const selections = { ...s.selections };
      delete selections[zone];
      const makeup = { ...s.makeup, [zone]: null };
      return { makeup, selections, modified: modifiedZones(makeup, selections, s.lookOrigin) };
    }),

  revertZone: (zone) =>
    set((s) => {
      if (s.fit) return s;
      const origin = s.lookOrigin;
      if (!origin) return s;
      const zones = new Set<MakeupZone>([zone]);
      for (const link of s.colorLinks) if (link.zones.includes(zone)) link.zones.forEach((z) => zones.add(z));
      const makeup = { ...s.makeup };
      const selections = { ...s.selections };
      for (const z of zones) {
        const back = origin.makeup[z];
        makeup[z] = back ? { ...back, intensity: s.makeup[z]?.intensity ?? back.intensity } : null;
        const sel = origin.selections[z];
        if (sel) selections[z] = sel;
        else delete selections[z];
      }
      return { makeup, selections, modified: modifiedZones(makeup, selections, origin) };
    }),

  startFit: (product, shade) => {
    const zone = product.makeupZone;
    const texture = product.texture;
    if (!zone || !texture || !isArPaintZone(zone)) return;
    set((s) => {
      const origin: FitOrigin = s.fitOrigin ?? {
        makeup: s.makeup,
        selections: s.selections,
        activeLook: s.activeLook,
        colorLinks: s.colorLinks,
        heroZones: s.heroZones,
        stepOrder: s.stepOrder,
        modified: s.modified,
        lookOrigin: s.lookOrigin,
      };
      const painted: ZoneSetting = {
        hex: shade.hex,
        texture,
        intensity: DEFAULT_INTENSITY[zone],
      };
      return {
        fit: { productId: product.id, shadeId: shade.id },
        fitOrigin: origin,
        makeup: { ...origin.makeup, [zone]: painted },
        selections: { ...origin.selections, [zone]: { productId: product.id, shadeId: shade.id } },
      };
    });
  },

  endFit: () =>
    set((s) => {
      const origin = s.fitOrigin;
      if (!origin) return { fit: null, fitOrigin: null };
      return {
        fit: null,
        fitOrigin: null,
        makeup: origin.makeup,
        selections: origin.selections,
        activeLook: origin.activeLook,
        colorLinks: origin.colorLinks,
        heroZones: origin.heroZones,
        stepOrder: origin.stepOrder,
        modified: origin.modified,
        lookOrigin: origin.lookOrigin,
      };
    }),

  reset: () =>
    set({
      makeup: EMPTY,
      selections: {},
      activeLook: null,
      colorLinks: [],
      heroZones: [],
      stepOrder: [],
      modified: [],
      lookOrigin: null,
      fit: null,
      fitOrigin: null,
    }),
}));
