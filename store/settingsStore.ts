import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { LanguagePreference } from '@/lib/i18n/languages';
import { persistStorage, STORAGE_KEYS } from '@/lib/storage';

interface SettingsState {
  language: LanguagePreference;
  /** User accepted the on-device camera try-on notice. */
  cameraConsent: boolean;
  setLanguage: (language: LanguagePreference) => void;
  setCameraConsent: (value: boolean) => void;
  reset: () => void;
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      language: 'system',
      cameraConsent: false,
      setLanguage: (language) => set({ language }),
      setCameraConsent: (cameraConsent) => set({ cameraConsent }),
      reset: () => set({ language: 'system', cameraConsent: false }),
    }),
    {
      name: STORAGE_KEYS.settings,
      storage: persistStorage,
      partialize: ({ language, cameraConsent }) => ({ language, cameraConsent }),
    }
  )
);
