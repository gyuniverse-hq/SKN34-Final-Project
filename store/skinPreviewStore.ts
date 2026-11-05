import { create } from 'zustand';
import type { SkinPreview } from '@/types/skin';

// Memory only: never attach persistence middleware to this store.
export const useSkinPreviewStore = create<{
  preview: SkinPreview | null;
  setPreview: (preview: SkinPreview) => void;
  clear: () => void;
}>((set) => ({ preview: null, setPreview: (preview) => set({ preview }), clear: () => set({ preview: null }) }));
