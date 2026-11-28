import { create } from 'zustand';
import type { CelebLook, Product } from '@/types';

export type LookPreviewDraft = {
  look: CelebLook;
  products: Product[];
  video: boolean;
};

export const useLookPreviewStore = create<{ draft: LookPreviewDraft | null }>(() => ({ draft: null }));
