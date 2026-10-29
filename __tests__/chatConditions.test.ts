import { extractChatConditions } from '@/lib/chatConditions';

describe('extractChatConditions', () => {
  it('extracts explicit shopping conditions without changing the message', () => {
    const input = '립 제품 중 2만 원 이하, 향료 없는 제품 추천해줘. 촉촉함 우선';
    expect(extractChatConditions(input)).toEqual([
      { kind: 'category', text: '립 제품', required: true, value: 'lip' },
      { kind: 'maxPrice', text: '2만 원 이하', required: true, value: 20000 },
      { kind: 'fragranceFree', text: '향료 없는', required: true },
      { kind: 'moisturizing', text: '촉촉함 우선', required: false },
    ]);
  });

  it.each([
    ['2만 5000원 이하 립 추천', 25000],
    ['립 20,000원 이하 추천', 20000],
    ['find a lip product up to KRW 15,000', 15000],
  ])('extracts the maximum reference price in %s', (message, value) => {
    expect(extractChatConditions(message).find((condition) => condition.kind === 'maxPrice')?.value).toBe(value);
  });

  it.each([
    '향료가 뭔가요?',
    '립 바르는 법 추천해줘',
    'How to use lip products?',
    '추천해줘',
  ])('does not invent filters for general questions: %s', (message) => {
    expect(extractChatConditions(message)).toEqual([]);
  });

  it('does not treat a price mention or a negated condition as a requirement', () => {
    const kinds = extractChatConditions('립 말고 블러셔 제품, 2만원짜리 향료 없는 건 아니야').map((c) => c.kind);
    expect(kinds).toEqual(['category']);
    expect(extractChatConditions('₩20,000 lip product').some((c) => c.kind === 'maxPrice')).toBe(false);
  });

  it('does not misrepresent multiple categories as mandatory at once', () => {
    expect(extractChatConditions('립 또는 블러셔 제품 추천해줘').filter((c) => c.kind === 'category')).toEqual([]);
  });

  it('supports explicit multilingual category and fragrance requests', () => {
    expect(extractChatConditions('香料無添加のリップをおすすめ').map((c) => c.kind)).toEqual(['category', 'fragranceFree']);
    expect(extractChatConditions('推荐不含香料的口红').map((c) => c.kind)).toEqual(['category', 'fragranceFree']);
    expect(extractChatConditions('recommend fragrance-free lip products').map((c) => c.kind)).toEqual(['category', 'fragranceFree']);
  });
});
