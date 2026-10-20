export const LANGUAGES = ['en', 'ko', 'ja', 'zh'] as const;
export type Language = (typeof LANGUAGES)[number];
export type LanguagePreference = Language | 'system';

export const LANGUAGE_LABELS: Record<Language, string> = {
  en: 'English',
  ko: '한국어',
  ja: '日本語',
  zh: '简体中文',
};

export function resolveLanguage(preference: LanguagePreference, deviceLanguageCode?: string | null): Language {
  if (preference !== 'system') return preference;
  const code = deviceLanguageCode?.toLowerCase();
  return (LANGUAGES as readonly string[]).includes(code ?? '') ? (code as Language) : 'en';
}
