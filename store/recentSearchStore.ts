import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { persistStorage, STORAGE_KEYS } from '@/lib/storage';

interface RecentSearchState {
  searches: string[];
  add: (query: string) => void;
  remove: (query: string) => void;
  clear: () => void;
}

export const useRecentSearchStore = create<RecentSearchState>()(
  persist((set) => ({
    searches: [],
    add: (query) => {
      const value = query.trim().slice(0, 80);
      if (!value) return;
      set((s) => ({ searches: [value, ...s.searches.filter((item) => item.toLocaleLowerCase() !== value.toLocaleLowerCase())].slice(0, 10) }));
    },
    remove: (query) => set((s) => ({ searches: s.searches.filter((item) => item !== query) })),
    clear: () => set({ searches: [] }),
  }), { name: STORAGE_KEYS.recentSearches, storage: persistStorage, version: 1 })
);
