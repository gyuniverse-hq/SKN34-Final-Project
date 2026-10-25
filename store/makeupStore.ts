import { create } from 'zustand';
import type { CelebLook, MakeupState, MakeupZone, Product, Shade } from '@/types';

export interface ZoneSelection {
  productId: string;
  shadeId: string;
}

/** Try-on zones in the AR panel's tab order. */
export const MAKEUP_ZONES: MakeupZone[] = ['lip', 'blush', 'eyeshadow', 'eyeliner', 'mascara', 'highlighter', 'contour'];

export const DEFAULT_INTENSITY: Record<MakeupZone, number> = {
  lip: 0.65,
  blush: 0.45,
  eyeshadow: 0.45,
  eyeliner: 0.85,
  mascara: 0.7,
  highlighter: 0.5,
  contour: 0.4,
};

interface MakeupStore {
  makeup: MakeupState;
  selections: Partial<Record<MakeupZone, ZoneSelection>>;
  activeLook: { id: string; title: string } | null;
  applyShade: (product: Product, shade: Shade) => void;
  applyLook: (look: CelebLook, products: Product[]) => void;
  setIntensity: (zone: MakeupZone, intensity: number) => void;
  clearZone: (zone: MakeupZone) => void;
  reset: () => void;
}

const EMPTY: MakeupState = {
  lip: null,
  blush: null,
  eyeshadow: null,
  eyeliner: null,
  mascara: null,
  highlighter: null,
  contour: null,
};

export const useMakeupStore = create<MakeupStore>((set) => ({
  makeup: EMPTY,
  selections: {},
  activeLook: null,

  applyShade: (product, shade) => {
    const zone = product.makeupZone;
    if (!zone) return;
    set((s) => ({
      makeup: {
        ...s.makeup,
        [zone]: {
          hex: shade.hex,
          texture: product.texture,
          intensity: s.makeup[zone]?.intensity ?? DEFAULT_INTENSITY[zone],
        },
      },
      selections: { ...s.selections, [zone]: { productId: product.id, shadeId: shade.id } },
      activeLook: null,
    }));
  },

  applyLook: (look, products) => {
    const selections: Partial<Record<MakeupZone, ZoneSelection>> = {};
    for (const item of look.items) {
      const product = products.find((p) => p.id === item.productId);
      if (product?.makeupZone && item.shadeId) {
        selections[product.makeupZone] = { productId: product.id, shadeId: item.shadeId };
      }
    }
    set({ makeup: { ...EMPTY, ...look.makeup }, selections, activeLook: { id: look.id, title: look.title } });
  },

  setIntensity: (zone, intensity) =>
    set((s) => {
      const current = s.makeup[zone];
      if (!current) return s;
      return { makeup: { ...s.makeup, [zone]: { ...current, intensity } } };
    }),

  clearZone: (zone) =>
    set((s) => {
      const selections = { ...s.selections };
      delete selections[zone];
      return { makeup: { ...s.makeup, [zone]: null }, selections, activeLook: null };
    }),

  reset: () => set({ makeup: EMPTY, selections: {}, activeLook: null }),
}));
