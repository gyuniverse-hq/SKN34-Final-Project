import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { persistStorage, STORAGE_KEYS } from '@/lib/storage';
import type { CompareItem } from '@/types/view';

export const MAX_COMPARE = 3;

interface CompareState {
  items: CompareItem[];
  /** One entry per product; re-adding replaces the shade. Returns false when the list is full. */
  add: (item: CompareItem) => boolean;
  remove: (productId: string) => void;
  clear: () => void;
}

export function addCompareItem(items: CompareItem[], item: CompareItem): CompareItem[] | null {
  if (items.some((i) => i.productId === item.productId)) {
    return items.map((i) => (i.productId === item.productId ? item : i));
  }
  return items.length >= MAX_COMPARE ? null : [...items, item];
}

export const useCompareStore = create<CompareState>()(
  persist(
    (set, get) => ({
      items: [],
      add: (item) => {
        const next = addCompareItem(get().items, item);
        if (!next) return false;
        set({ items: next });
        return true;
      },
      remove: (productId) => set((s) => ({ items: s.items.filter((i) => i.productId !== productId) })),
      clear: () => set({ items: [] }),
    }),
    { name: STORAGE_KEYS.compare, storage: persistStorage, version: 1 }
  )
);
