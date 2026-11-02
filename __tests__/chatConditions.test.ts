import { conditionsFromChatFilters, extractChatConditions } from '@/lib/chatConditions';

describe('extractChatConditions', () => {
  it('displays retained ingredient predicates from effective server filters', () => {
    const conditions = conditionsFromChatFilters({ category: null, maxPriceKRW: null,
      fragranceFree: false, moisturizing: false, query: '',
      ingredientConditions: [{ ingredientName: 'Alcohol', operator: 'excludes' }],
    }, (key) => key);
    expect(conditions).toEqual([{ kind: 'ingredient', required: true, text: 'Alcohol · chat.ingredient.excludes' }]);
  });
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
    ['Recommend a moisturizing lip product under ₩20,000.', 19999],
    ['find a lip product less than KRW 20,000', 19999],
  ])('extracts the maximum reference price in %s', (message, value) => {
    expect(extractChatConditions(message).find((condition) => condition.kind === 'maxPrice')?.value).toBe(value);
  });

  it.each([
    ['2만 원 이하 촉촉한 립 제품 추천해줘', '촉촉한'],
    ['Recommend a moisturizing lip product under ₩20,000.', 'moisturizing'],
  ])('recognizes the moisturizing preference in %s', (message, text) => {
    expect(extractChatConditions(message)).toContainEqual({ kind: 'moisturizing', text, required: false });
  });

  it.each([
    '안 촉촉한 립 제품 추천해줘',
    '촉촉한 립 제품 말고 블러셔 추천해줘',
    'recommend a lip product that is not moisturizing',
    'recommend a product that is not a moisturizing lip product',
  ])('does not label a negated moisturizing request as preferred: %s', (message) => {
    expect(extractChatConditions(message).some((condition) => condition.kind === 'moisturizing')).toBe(false);
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
    expect(extractChatConditions('립 빼고 블러셔 제품 추천').filter((c) => c.kind === 'category')).toEqual([
      { kind: 'category', text: '블러셔', required: true, value: 'cheek' },
    ]);
    expect(extractChatConditions('recommend a lip product not under ₩20,000').some((c) => c.kind === 'maxPrice')).toBe(false);
  });

  it('does not misrepresent multiple categories as mandatory at once', () => {
    expect(extractChatConditions('립 또는 블러셔 제품 추천해줘').filter((c) => c.kind === 'category')).toEqual([]);
  });

  it.each([
    '립은 빼고 추천해줘',
    '립 제품은 제외해줘',
    '립을 빼고 추천해줘',
  ])('does not present an excluded category as required: %s', (message) => {
    expect(extractChatConditions(message).some((condition) => condition.kind === 'category')).toBe(false);
  });

  it('keeps the included category when another category with a particle is excluded', () => {
    expect(extractChatConditions('립은 빼고 블러셔 제품 추천해줘').filter((condition) => condition.kind === 'category')).toEqual([
      { kind: 'category', text: '블러셔', required: true, value: 'cheek' },
    ]);
  });

  it('supports explicit multilingual category and fragrance requests', () => {
    expect(extractChatConditions('香料無添加のリップをおすすめ').map((c) => c.kind)).toEqual(['category', 'fragranceFree']);
    expect(extractChatConditions('推荐不含香料的口红').map((c) => c.kind)).toEqual(['category', 'fragranceFree']);
    expect(extractChatConditions('recommend fragrance-free lip products').map((c) => c.kind)).toEqual(['category', 'fragranceFree']);
  });
});
