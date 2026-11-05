import { en } from '@/lib/i18n/en';
import { ja } from '@/lib/i18n/ja';
import { ko } from '@/lib/i18n/ko';
import { resolveLanguage } from '@/lib/i18n/languages';
import { zh } from '@/lib/i18n/zh';

jest.mock('expo-localization', () => ({ useLocales: () => [{ languageCode: 'en' }] }));

describe('i18n', () => {
  it.each([
    ['ko', ko],
    ['ja', ja],
    ['zh', zh],
  ])('%s has every key with matching placeholders', (_name, dict) => {
    for (const key of Object.keys(en) as (keyof typeof en)[]) {
      expect(dict[key]).toBeTruthy();
      const placeholders = (s: string) => (s.match(/\{\w+\}/g) ?? []).sort();
      expect(placeholders(dict[key])).toEqual(placeholders(en[key]));
    }
  });

  it('resolves language preference', () => {
    expect(resolveLanguage('system', 'ja')).toBe('ja');
    expect(resolveLanguage('system', 'fr')).toBe('en');
    expect(resolveLanguage('system', null)).toBe('en');
    expect(resolveLanguage('ko', 'ja')).toBe('ko');
  });

  it('interpolates params', () => {
    const { translate } = require('@/lib/i18n') as typeof import('@/lib/i18n');
    expect(translate('en', 'shop.shadeCount', { count: 3 })).toBe('3 shades');
  });
});
