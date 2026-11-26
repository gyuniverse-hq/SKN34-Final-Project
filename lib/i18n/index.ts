import { useLocales } from 'expo-localization';
import { useCallback, useSyncExternalStore } from 'react';
import { useSettingsStore } from '@/store/settingsStore';
import { en, type Dictionary, type TranslationKey } from './en';
import { ja } from './ja';
import { ko } from './ko';
import { resolveLanguage, type Language } from './languages';
import { zh } from './zh';

export * from './languages';
export type { TranslationKey };

const DICTIONARIES: Record<Language, Dictionary> = { en, ko, ja, zh };
const subscribeToHydration = () => () => {};
const getServerLanguage = () => resolveLanguage('system');

export function translate(
  language: Language,
  key: TranslationKey,
  params?: Record<string, string | number>
): string {
  let text = DICTIONARIES[language][key] ?? en[key] ?? key;
  if (params) {
    for (const [name, value] of Object.entries(params)) {
      text = text.replaceAll(`{${name}}`, String(value));
    }
  }
  return text;
}

export function useI18n() {
  const preference = useSettingsStore((s) => s.language);
  const locales = useLocales();
  // Server HTML and the browser's initial render must use the same language.
  const language = useSyncExternalStore(
    subscribeToHydration,
    () => resolveLanguage(preference, locales[0]?.languageCode),
    getServerLanguage,
  );
  const t = useCallback(
    (key: TranslationKey, params?: Record<string, string | number>) => translate(language, key, params),
    [language]
  );
  return { t, language };
}
