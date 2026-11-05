import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { persistStorage, STORAGE_KEYS } from '@/lib/storage';
import type { ShoppingList } from '@/types';

const MAX_LISTS = 30;

interface ShoppingListState {
  lists: ShoppingList[];
  save: (list: ShoppingList) => void;
  remove: (id: string) => void;
  clear: () => void;
}

export const useShoppingListStore = create<ShoppingListState>()(
  persist(
    (set) => ({
      lists: [],
      save: (list) => set((s) => ({ lists: [list, ...s.lists].slice(0, MAX_LISTS) })),
      remove: (id) => set((s) => ({ lists: s.lists.filter((l) => l.id !== id) })),
      clear: () => set({ lists: [] }),
    }),
    { name: STORAGE_KEYS.lists, storage: persistStorage, version: 1 }
  )
);
