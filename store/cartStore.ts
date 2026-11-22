import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { persistStorage, STORAGE_KEYS } from '@/lib/storage';
import type { CartItem } from '@/types';

export const MAX_QUANTITY = 20;

export function cartLineKey(item: Pick<CartItem, 'productId' | 'shadeId'>) {
  return `${item.productId}::${item.shadeId ?? ''}`;
}

export interface PendingPayment {
  orderId: string;
  userId: string;
  items: CartItem[];
}

interface CartState {
  items: CartItem[];
  pendingPayment: PendingPayment | null;
  add: (item: Omit<CartItem, 'quantity'>, quantity?: number) => void;
  addMany: (items: Omit<CartItem, 'quantity'>[]) => void;
  setQuantity: (key: string, quantity: number) => void;
  remove: (key: string) => void;
  clear: () => void;
  reset: () => void;
  setPendingPayment: (payment: PendingPayment) => void;
  completePayment: (orderId: string) => void;
}

function addInto(items: CartItem[], item: Omit<CartItem, 'quantity'>, quantity: number): CartItem[] {
  const key = cartLineKey(item);
  const existing = items.find((i) => cartLineKey(i) === key);
  const previousQuantity = existing?.quantity ?? 0;
  const nextQuantity = Math.min(previousQuantity + quantity, MAX_QUANTITY);
  const next = { ...(existing ?? item), quantity: nextQuantity };
  if (existing?.arCartSources || item.arCartSources) {
    const sources = Array.from({ length: nextQuantity }, (_, index) => index < previousQuantity
      ? existing?.arCartSources?.[index] ?? null
      : item.arCartSources?.[index - previousQuantity] ?? null);
    if (sources.some(Boolean)) next.arCartSources = sources;
    else delete next.arCartSources;
  }
  return existing ? items.map(i => i === existing ? next : i) : [...items, next];
}

export const useCartStore = create<CartState>()(
  persist(
    (set) => ({
      items: [],
      pendingPayment: null,
      add: (item, quantity = 1) => set((s) => ({ items: addInto(s.items, item, quantity) })),
      addMany: (items) =>
        set((s) => ({ items: items.reduce((acc, item) => addInto(acc, item, 1), s.items) })),
      setQuantity: (key, quantity) =>
        set((s) => ({
          items:
            quantity <= 0
              ? s.items.filter((i) => cartLineKey(i) !== key)
              : s.items.map((i) => {
                if (cartLineKey(i) !== key) return i;
                const next = { ...i, quantity: Math.min(quantity, MAX_QUANTITY) };
                // Remove the last units first. Later increases create unattributed units.
                const sources = i.arCartSources?.slice(0, next.quantity);
                if (sources?.some(Boolean)) next.arCartSources = sources;
                else delete next.arCartSources;
                return next;
              }),
        })),
      remove: (key) => set((s) => ({ items: s.items.filter((i) => cartLineKey(i) !== key) })),
      clear: () => set({ items: [] }),
      reset: () => set({ items: [], pendingPayment: null }),
      setPendingPayment: (payment) => set({ pendingPayment: payment }),
      completePayment: (orderId) =>
        set((s) => {
          if (s.pendingPayment?.orderId !== orderId) return s;
          const paid = new Map(s.pendingPayment.items.map((item) => [cartLineKey(item), item]));
          return {
            // Preserve any line edited while payment was open instead of deleting new user changes.
            items: s.items.filter((item) => {
              const ordered = paid.get(cartLineKey(item));
              return ordered?.quantity !== item.quantity ||
                JSON.stringify(ordered?.arCartSources) !== JSON.stringify(item.arCartSources);
            }),
            pendingPayment: null,
          };
        }),
    }),
    { name: STORAGE_KEYS.cart, storage: persistStorage, version: 1 }
  )
);

export function selectCartCount(state: CartState) {
  return state.items.reduce((sum, i) => sum + i.quantity, 0);
}
