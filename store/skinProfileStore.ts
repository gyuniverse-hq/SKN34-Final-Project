import { create } from 'zustand';
import type { SkinProfile } from '@/types/skin';
import { readSkinProfile, writeSkinProfile } from '@/lib/skinProfile';

// Explicit awaited writes: persist middleware alone cannot acknowledge a failed disk write.
let revision = 0;
export const useSkinProfileStore = create<{
  profile: SkinProfile | null;
  owner: string | null;
  hydrate: (owner?: string | null) => Promise<void>;
  save: (profile: SkinProfile, owner?: string | null) => Promise<void>;
  reset: () => void;
}>((set) => ({
  profile: null,
  owner: null,
  hydrate: async (owner = null) => {
    const before = ++revision;
    const profile = await readSkinProfile(owner);
    if (before === revision) set({ owner, profile });
  },
  save: async (profile, owner = null) => {
    await writeSkinProfile(profile, owner);
    revision++;
    set({ owner, profile });
  },
  reset: () => { revision++; set({ profile: null }); },
}));
