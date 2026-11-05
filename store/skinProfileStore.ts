import { create } from 'zustand';
import type { SkinProfile } from '@/types/skin';
import { readSkinProfile, writeSkinProfile } from '@/lib/skinProfile';

// Explicit awaited writes: persist middleware alone cannot acknowledge a failed disk write.
let revision = 0;
export const useSkinProfileStore = create<{
  profile: SkinProfile | null;
  hydrate: () => Promise<void>;
  save: (profile: SkinProfile) => Promise<void>;
  reset: () => void;
}>((set) => ({
  profile: null,
  hydrate: async () => {
    const before = revision;
    const profile = await readSkinProfile();
    if (before === revision) set({ profile });
  },
  save: async (profile) => {
    await writeSkinProfile(profile);
    revision++;
    set({ profile });
  },
  reset: () => { revision++; set({ profile: null }); },
}));
