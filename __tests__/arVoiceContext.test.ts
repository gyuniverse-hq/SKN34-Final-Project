import { arVoiceKeywords, encodeArVoiceContext } from '@/lib/arVoiceContext';
import type { Product } from '@/types';

const catalog = require('@/lib/devCatalog/oyCatalog.json').products as Product[];

it('uses the current palette window and the exact worn shade from the catalog', () => {
  const lip = catalog.find(product => product.makeupZone === 'lip' && product.shades.length > 8)!;
  const blush = catalog.find(product => product.makeupZone === 'blush' && product.shades.length > 1)!;
  const palette = lip.shades.map(shade => ({ product: lip, shade }));
  const keywords = arVoiceKeywords([lip, blush], palette, 0, [
    { productId: blush.id, shadeId: blush.shades[1].id },
    { productId: 'missing', shadeId: 'missing' },
  ]);
  expect(keywords).toContain(lip.brand);
  expect(keywords).toContain(lip.shades[0].name);
  expect(keywords).toContain(lip.shades[3].name);
  expect(keywords).not.toContain(lip.shades[8].name);
  expect(keywords).toContain(blush.nameKo || blush.name);
  expect(keywords).toContain(blush.shades[1].name);
});

it('bounds context and skips duplicate or unsupported catalog terms', () => {
  const encoded = encodeArVoiceContext('zh', [
    '샤인 립', ' 샤인립 ', '두\n줄', '＜필드＞', ' ',
    ...Array.from({ length: 30 }, (_, index) => '화장'.repeat(28) + index),
  ]);
  const { language, keywords } = JSON.parse(decodeURIComponent(encoded));
  expect(encoded.length).toBeLessThanOrEqual(4096);
  expect(keywords.length).toBeLessThanOrEqual(24);
  expect(language).toBe('zh');
  expect(keywords[0]).toBe('샤인 립');
  expect(keywords).not.toContain('샤인립');
  expect(keywords.every((term: string) => !/[<>\r\n]/.test(term))).toBe(true);
});
