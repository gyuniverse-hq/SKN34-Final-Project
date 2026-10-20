import { useLocales } from 'expo-localization';
import { useCallback } from 'react';
import { useSettingsStore } from '@/store/settingsStore';
import { en, type Dictionary, type TranslationKey } from './en';
import { ja } from './ja';
import { ko } from './ko';
import { resolveLanguage, type Language } from './languages';
import { zh } from './zh';

export * from './languages';
export type { TranslationKey };

const DICTIONARIES: Record<Language, Dictionary> = { en, ko, ja, zh };

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
  const language = resolveLanguage(preference, locales[0]?.languageCode);
  const t = useCallback(
    (key: TranslationKey, params?: Record<string, string | number>) => translate(language, key, params),
    [language]
  );
  return { t, language };
}
