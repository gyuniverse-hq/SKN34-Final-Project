import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { persistStorage, STORAGE_KEYS } from '@/lib/storage';
import type { CartItem } from '@/types';

export const MAX_QUANTITY = 20;

export function cartLineKey(item: Pick<CartItem, 'productId' | 'shadeId'>) {
  return `${item.productId}::${item.shadeId ?? ''}`;
}

interface CartState {
  items: CartItem[];
  add: (item: Omit<CartItem, 'quantity'>, quantity?: number) => void;
  addMany: (items: Omit<CartItem, 'quantity'>[]) => void;
  setQuantity: (key: string, quantity: number) => void;
  remove: (key: string) => void;
  clear: () => void;
}

function addInto(items: CartItem[], item: Omit<CartItem, 'quantity'>, quantity: number): CartItem[] {
  const key = cartLineKey(item);
  const existing = items.find((i) => cartLineKey(i) === key);
  if (existing) {
    return items.map((i) =>
      cartLineKey(i) === key
        ? { ...i, quantity: Math.min(i.quantity + quantity, MAX_QUANTITY) }
        : i
    );
  }
  return [...items, { ...item, quantity: Math.min(quantity, MAX_QUANTITY) }];
}

export const useCartStore = create<CartState>()(
  persist(
    (set) => ({
      items: [],
      add: (item, quantity = 1) => set((s) => ({ items: addInto(s.items, item, quantity) })),
      addMany: (items) =>
        set((s) => ({ items: items.reduce((acc, item) => addInto(acc, item, 1), s.items) })),
      setQuantity: (key, quantity) =>
        set((s) => ({
          items:
            quantity <= 0
              ? s.items.filter((i) => cartLineKey(i) !== key)
              : s.items.map((i) =>
                  cartLineKey(i) === key ? { ...i, quantity: Math.min(quantity, MAX_QUANTITY) } : i
                ),
        })),
      remove: (key) => set((s) => ({ items: s.items.filter((i) => cartLineKey(i) !== key) })),
      clear: () => set({ items: [] }),
    }),
    { name: STORAGE_KEYS.cart, storage: persistStorage, version: 1 }
  )
);

export function selectCartCount(state: CartState) {
  return state.items.reduce((sum, i) => sum + i.quantity, 0);
}
