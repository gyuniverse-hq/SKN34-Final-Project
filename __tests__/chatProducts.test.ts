import { createElement } from 'react';
import { ScrollView, Text, View } from 'react-native';
import { act, create, type ReactTestInstance, type ReactTestRenderer } from 'react-test-renderer';
import { ChatProducts, CompoundProductCards } from '@/components/chat/ChatProducts';
import { ProductCompareSheet } from '@/components/chat/ProductCompareSheet';
import { ProductImage } from '@/components/ui/ProductImage';
import type { ChatCondition } from '@/lib/chatConditions';
import type { ChatOptionSearch, CompoundConsultation, Product } from '@/types';

jest.mock('@/lib/i18n', () => ({ useI18n: () => ({
  language: 'ko',
  t: (key: string, params?: Record<string, number | string>) => {
    if (key === 'chat.candidateNumber') return `${key}:${params?.index}`;
    if (key.startsWith('chat.compound.')) {
      const value = jest.requireActual('@/lib/i18n/ko').ko[key] as string;
      return value.replace(/\{(\w+)\}/g, (_, name) => String(params?.[name]));
    }
    return key;
  },
}) }));
jest.mock('@/components/ui/ProductImage', () => ({ ProductImage: () => null }));

const lip: Product = {
  id: 'lip-1', brand: 'Brand', name: 'Lip product', nameKo: '립 제품', category: 'lip',
  makeupZone: 'lip', texture: 'satin', priceKRW: 15000, volume: '3g',
  shades: [{ id: 'shade-1', name: 'Rose', hex: '#aa2244' }],
  description: '', keyIngredients: ['Panthenol'], tags: [], imageUrl: 'https://example.com/lip.jpg', searchKeyword: '',
};
const care: Product = {
  ...lip, id: 'care-1', name: 'Care product', category: 'skincare', makeupZone: null,
  priceKRW: 25000, shades: [], imageUrl: 'https://example.com/care.jpg', keyIngredients: [],
};
const conditions: ChatCondition[] = [
  { kind: 'category', text: 'lip', required: true, value: 'lip' },
  { kind: 'maxPrice', text: 'under 20000', required: true, value: 20000 },
  { kind: 'fragranceFree', text: 'fragrance-free', required: true },
];

function textRows(renderer: ReactTestRenderer): string[] {
  return renderer.root.findAllByType(Text).map((item) => Array.isArray(item.props.children)
    ? item.props.children.join('')
    : String(item.props.children));
}

function conditionRows(renderer: ReactTestRenderer): string[] {
  return renderer.root.findAllByType(View).flatMap((item) =>
    item.props.accessible && typeof item.props.accessibilityLabel === 'string' ? [item.props.accessibilityLabel] : []);
}

function buttonWithText(root: ReactTestInstance, text: string) {
  const label = root.findAllByType(Text).find((item) => item.props.children === text);
  let button = label?.parent;
  while (button && typeof button.props.onPress !== 'function') button = button.parent;
  if (!button) throw new Error(`Button not found: ${text}`);
  return button;
}

async function renderProducts(props: Partial<Parameters<typeof ChatProducts>[0]> = {}) {
  let renderer!: ReactTestRenderer;
  const onOpenProduct = jest.fn();
  const onOpenAr = jest.fn();
  await act(async () => {
    renderer = create(createElement(ChatProducts, {
      products: [lip, care], loading: false, failed: false, missingCount: 0,
      conditions, showIngredients: true, onRetry: jest.fn(), onOpenProduct, onOpenAr, ...props,
    }));
  });
  return { renderer, onOpenProduct, onOpenAr };
}

describe('chat product cards', () => {
  it('shows only exact verified options with their original ranks, observed price and ingredient checks', async () => {
    type Option = CompoundConsultation['options'][number];
    const option = (rank: number, outcome: Option['outcome']): Option => ({
      candidate: { rank, productId: 'care', optionId: 'opt-' + rank, optionName: 'Bottle ' + rank,
        productName: 'Care product', brand: 'Brand', hasShades: false, dataVersion: 'v4', ingredientCodes: ['NOT_FULL_LIST'] },
      outcome,
      verification: { productId: 'care', optionId: 'opt-' + rank, shadeId: null, sourceVersion: 'cat-1',
        synthetic: false, group: 'ELIGIBLE', checks: [
          { condition: 'ingredient', verdict: 'MATCH', operator: 'excludes', ingredientName: '향료', reason: 'verified' },
          { condition: 'price', verdict: 'MATCH', reason: 'within_budget' },
        ], price: { amountKRW: 18000, observedBasis: 'collected_snapshot', requestedBasis: 'collected_snapshot',
          observedAt: '2026-11-01T01:00:00Z', checkedAt: '2026-11-02', sourceRef: 'https://shop.example.test/sale', sourceVersion: 'private-version' } },
    });
    const wrongOption = option(1, 'eligible');
    wrongOption.verification!.optionId = 'different';
    const incomplete = option(4, 'eligible');
    incomplete.verification!.group = 'REFERENCE_ONLY';
    const undated = option(10, 'eligible');
    Object.assign(undated.verification!.price!, { observedAt: null, observedBasis: 'catalog_reference' });
    const result: CompoundConsultation = {
      planVersion: 1, goal: { goals: ['dryness'], wantsProducts: true, wantsKnowledge: true,
        fragranceFree: false, maxPriceKRW: 20000, excludedIngredients: ['향료'], unsupportedConditions: [] },
      options: [undated, option(8, 'eligible'), wrongOption, incomplete,
        option(5, 'excluded'), option(6, 'unknown'), option(7, 'failed')], batches: [], limitations: [],
    };
    const onOpenProduct = jest.fn();
    let renderer!: ReactTestRenderer;
    await act(async () => { renderer = create(createElement(CompoundProductCards, { result, onOpenProduct })); });
    const rows = textRows(renderer);
    expect(rows.filter((row) => row.startsWith('Care product · '))).toEqual(['Care product · Bottle 8', 'Care product · Bottle 10']);
    expect(rows).toContain('18,000원');
    expect(rows).toContain('전성분표에 향료 표기 없음');
    expect(rows.join(' ')).not.toMatch(/2026-11|shop\.example|private-version|NOT_FULL_LIST|전체 후보 중/);
    const toggles = renderer.root.findAllByType(Text).filter((item) => item.props.children === '가격 정보');
    const openPrice = async (index: number) => {
      let button = toggles[index].parent;
      while (button && typeof button.props.onPress !== 'function') button = button.parent;
      await act(async () => { button!.props.onPress(); });
    };
    await openPrice(0);
    expect(textRows(renderer)).toEqual(expect.arrayContaining(['2026. 11. 1. 확인', '판매처 자료 · shop.example.test']));
    await openPrice(1);
    expect(textRows(renderer)).toEqual(expect.arrayContaining(['상품 카탈로그에 등록된 참고 가격이에요.', '가격을 확인한 날짜는 알려지지 않았어요.']));
    expect(textRows(renderer).join(' ')).not.toMatch(/2026\. 11\. 2\.|private-version|https:\/\//);
    await act(async () => { buttonWithText(renderer.root, 'chat.option.scopeShow').props.onPress(); });
    expect(textRows(renderer)).toContain('Care product · 전체 후보 중 8위');
    await act(async () => { buttonWithText(renderer.root, 'styleLooks.openProduct').props.onPress(); });
    expect(onOpenProduct).toHaveBeenCalledWith('care', undefined);
    await act(async () => { renderer.unmount(); });
  });
  it('keeps unlinked video products in the carousel without inventing a detail link', async () => {
    const sourceProducts = [
      { label: '원본 립', zone: 'lip', productId: lip.id, mappingStatus: 'product_only' as const, catalogValid: false, arEligible: false },
      { label: '원본 미연결 제품', zone: 'base', mappingStatus: 'unknown' as const, catalogValid: false, arEligible: false },
      { label: '원본 스킨케어', zone: 'unknown', productId: care.id, mappingStatus: 'product_only' as const, catalogValid: false, arEligible: false },
    ];
    const { renderer } = await renderProducts({ sourceProducts, conditions: [], showIngredients: false });
    const rows = textRows(renderer);
    expect(rows).toContain('원본 미연결 제품');
    expect(rows).toContain('chat.style.mappingNotLinked');
    expect(rows.some((row) => row.includes('1 / 3'))).toBe(true);
    expect(renderer.root.findAllByType(ProductImage)).toHaveLength(2);
    await act(async () => { renderer.unmount(); });
  });
  it('shows original candidate numbering and explicitly partial ingredient evidence', async () => {
    const { renderer } = await renderProducts({ products: [lip], candidateOrder: ['another', lip.id],
      evidence: [{ productId: lip.id, source: 'catalog_api', ingredientCoverage: 'key_only', fragranceStatus: 'unknown' }] });
    const rows = textRows(renderer);
    expect(rows).toContain('chat.candidateNumber:2');
    expect(rows).toContain('chat.catalogEvidence');
    expect(rows).toContain('chat.keyOnlyEvidence');
    expect(rows).toContain('chat.option.registeredPrice ₩15,000');
    expect(conditionRows(renderer).some((row) => row.includes('chat.conditionUnknown'))).toBe(true);
    await act(async () => { renderer.unmount(); });
  });
  it('shows catalog data and compares explicit conditions without inferring fragrance safety', async () => {
    const { renderer } = await renderProducts();
    const rows = textRows(renderer);
    expect(rows).toContain('Lip product');
    expect(rows).toContain('chat.referencePrice ₩15,000');
    expect(rows).toContain('shop.cat.lip');
    expect(rows).toContain('product.keyIngredients: Panthenol');
    expect(rows).toContain('chat.ui.keyIngredientsNotice');
    expect(rows).toContain('chat.ui.ingredientUnavailable');
    expect(conditionRows(renderer)).toContain('lip · chat.conditionMet');
    expect(conditionRows(renderer)).toContain('lip · chat.conditionNotMet');
    expect(conditionRows(renderer)).toContain('under 20000 · chat.conditionMet (chat.conditionPriceBasis)');
    expect(conditionRows(renderer)).toContain('under 20000 · chat.conditionNotMet (chat.conditionPriceBasis)');
    expect(conditionRows(renderer).filter((row) => row === 'fragrance-free · chat.conditionUnknown')).toHaveLength(2);
    expect(renderer.root.findAllByType(ProductImage).map((node) => node.props.uri))
      .toEqual(['https://example.com/lip.jpg', 'https://example.com/care.jpg']);
    await act(async () => { renderer.unmount(); });
  });

  it('separates candidates with unknown required conditions from confirmed mismatches', async () => {
    const { renderer } = await renderProducts({ products: [care, lip] });
    const rows = textRows(renderer);
    expect(rows.indexOf('chat.ui.candidatesUnverified')).toBeLessThan(rows.indexOf('Lip product'));
    expect(rows.indexOf('Lip product')).toBeLessThan(rows.indexOf('chat.ui.candidatesMismatched'));
    expect(rows.indexOf('chat.ui.candidatesMismatched')).toBeLessThan(rows.indexOf('Care product'));
    expect(rows).not.toContain('chat.ui.candidatesMatched');
    expect(rows).toContain('chat.ui.partialConditionsNotice');
    await act(async () => { renderer.unmount(); });
  });

  it.each([
    { kind: 'category', text: 'category', required: true },
    { kind: 'category', text: 'category', required: true, value: 'not-a-category' },
  ] as ChatCondition[])('does not treat an invalid category condition as a mismatch', async (condition) => {
    const { renderer } = await renderProducts({ products: [lip], conditions: [condition] });
    const rows = textRows(renderer);
    expect(conditionRows(renderer)).toContain('category · chat.conditionUnknown');
    expect(rows).toContain('chat.ui.candidatesUnverified');
    expect(rows).not.toContain('chat.ui.candidatesMismatched');
    await act(async () => { renderer.unmount(); });
  });

  it.each(['not-a-category', undefined])('does not treat a missing or invalid product category as a confirmed mismatch: %s', async (category) => {
    const invalidProduct = { ...lip, category } as unknown as Product;
    const { renderer } = await renderProducts({ products: [invalidProduct], conditions: [conditions[0]] });
    const rows = textRows(renderer);
    expect(conditionRows(renderer)).toContain('lip · chat.conditionUnknown');
    expect(rows).toContain('chat.ui.candidatesUnverified');
    expect(rows).not.toContain('chat.ui.candidatesMismatched');
    expect(renderer.root.findByType(ProductImage).props.category).toBeUndefined();
    expect(rows).not.toContain('shop.cat.not-a-category');
    await act(async () => { renderer.unmount(); });
  });

  it('groups matched candidates independently of an unverified preference', async () => {
    const { renderer } = await renderProducts({
      products: [care, lip],
      conditions: [conditions[0], { kind: 'moisturizing', text: 'hydrating', required: false }],
    });
    const rows = textRows(renderer);
    expect(rows.indexOf('chat.ui.candidatesMatched')).toBeLessThan(rows.indexOf('Lip product'));
    expect(rows.indexOf('Lip product')).toBeLessThan(rows.indexOf('chat.ui.candidatesMismatched'));
    expect(conditionRows(renderer)).toContain('hydrating (chat.ui.preferred) · chat.conditionUnknown');
    await act(async () => { renderer.unmount(); });
  });

  it('does not display an unavailable reference price as zero or as a matched condition', async () => {
    const { renderer } = await renderProducts({ products: [{ ...lip, priceKRW: 0 }], conditions: [conditions[1]] });
    const rows = textRows(renderer);
    expect(rows).toContain('chat.referencePrice chat.conditionUnknown');
    expect(conditionRows(renderer)).toContain('under 20000 · chat.conditionUnknown (chat.conditionPriceBasis)');
    expect(rows).toContain('chat.ui.candidatesUnverified');
    expect(rows).not.toContain('chat.ui.candidatesMatched');
    await act(async () => { renderer.unmount(); });
  });

  it('passes missing images to the existing labelled image placeholder', async () => {
    const { renderer } = await renderProducts({ products: [{ ...lip, imageUrl: '' }] });
    expect(renderer.root.findByType(ProductImage).props.uri).toBe('');
    expect(renderer.root.findByType(ProductImage).props.compact).toBeUndefined();
    await act(async () => { renderer.unmount(); });
  });

  it('never replaces a real product image with the preview artwork while actions are enabled', async () => {
    const { renderer } = await renderProducts({ products: [lip], previewImage: 123 });
    expect(renderer.root.findByType(ProductImage).props.uri).toBe('https://example.com/lip.jpg');
    await act(async () => { renderer.unmount(); });
  });

  it('distinguishes a partially missing product from a load error and retries the error', async () => {
    const onRetry = jest.fn();
    const { renderer } = await renderProducts({ products: [lip], failed: true, missingCount: 1, onRetry });
    expect(textRows(renderer)).toContain('chat.productLoadFailed');
    expect(textRows(renderer)).not.toContain('chat.productMissing');
    await act(async () => { buttonWithText(renderer.root, 'chat.productRetry').props.onPress(); });
    expect(onRetry).toHaveBeenCalledTimes(1);
    await act(async () => {
      renderer.update(createElement(ChatProducts, {
        products: [lip], loading: false, failed: false, missingCount: 1, conditions,
        showIngredients: false, onRetry, onOpenProduct: jest.fn(), onOpenAr: jest.fn(),
      }));
    });
    expect(textRows(renderer)).toContain('chat.productMissing');
    expect(textRows(renderer)).not.toContain('chat.productLoadFailed');
    await act(async () => { renderer.unmount(); });
  });

  it('offers the detail action with the correct product id and AR guidance only for eligible products', async () => {
    const { renderer, onOpenProduct } = await renderProducts();
    expect(textRows(renderer).filter((row) => row === 'chat.tryOnAtDetail')).toHaveLength(1);
    const button = renderer.root.findByProps({ accessibilityLabel: 'Brand Care product, chat.openProduct' });
    await act(async () => { button.props.onPress(); });
    expect(onOpenProduct).toHaveBeenCalledWith('care-1', undefined);
    await act(async () => { renderer.unmount(); });
  });

  it('opens AR only after choosing an actual eligible shade', async () => {
    const { renderer, onOpenAr } = await renderProducts();
    expect(textRows(renderer)).not.toContain('chat.trySelectedShade');
    await act(async () => { buttonWithText(renderer.root, 'Rose').props.onPress(); });
    expect(textRows(renderer).filter((row) => row === 'chat.trySelectedShade')).toHaveLength(1);
    await act(async () => { buttonWithText(renderer.root, 'chat.trySelectedShade').props.onPress(); });
    expect(onOpenAr).toHaveBeenCalledWith('lip-1', 'shade-1');
    await act(async () => { renderer.unmount(); });
  });

  it('passes the selected non-first shade to product details', async () => {
    const product = { ...lip, shades: [...lip.shades, { id: 'shade-2', name: 'Second', hex: '#445566' }] };
    const { renderer, onOpenProduct } = await renderProducts({ products: [product] });
    await act(async () => { buttonWithText(renderer.root, 'Second').props.onPress(); });
    await act(async () => { renderer.root.findByProps({ accessibilityLabel: 'Brand Lip product, chat.openProduct' }).props.onPress(); });
    expect(onOpenProduct).toHaveBeenCalledWith('lip-1', 'shade-2');
    await act(async () => { renderer.unmount(); });
  });

  it('shows disabled actions in the development preview without invoking product or AR navigation', async () => {
    const { renderer, onOpenProduct, onOpenAr } = await renderProducts({ products: [lip], disabledActions: true });
    const detail = renderer.root.findByProps({ accessibilityLabel: 'Brand Lip product, chat.openProduct' });
    const ar = renderer.root.findByProps({ accessibilityLabel: 'chat.trySelectedShade' });
    expect(detail.props.disabled).toBe(true);
    expect(detail.props.accessibilityState.disabled).toBe(true);
    expect(detail.props.onPress).toBeUndefined();
    expect(ar.props.disabled).toBe(true);
    expect(ar.props.accessibilityState.disabled).toBe(true);
    expect(ar.props.onPress).toBeUndefined();
    await act(async () => { buttonWithText(renderer.root, 'Rose').props.onPress(); });
    expect(renderer.root.findByProps({ accessibilityLabel: 'chat.trySelectedShade' }).props.disabled).toBe(true);
    expect(onOpenProduct).not.toHaveBeenCalled();
    expect(onOpenAr).not.toHaveBeenCalled();
    await act(async () => { renderer.unmount(); });
  });

  it('does not offer AR when a product id or its shade id is invalid', async () => {
    const badProduct = { ...lip, id: '../bad' };
    const badShade = { ...lip, id: 'lip-2', shades: [{ id: '../bad', name: 'Invalid shade', hex: '#000000' }] };
    const { renderer } = await renderProducts({ products: [badProduct, badShade] });
    expect(textRows(renderer)).not.toContain('chat.trySelectedShade');
    expect(textRows(renderer)).not.toContain('chat.selectShade');
    expect(textRows(renderer).filter((row) => row === 'chat.openProduct ›')).toHaveLength(1);
    await act(async () => { renderer.unmount(); });
  });

  it('does not offer AR when the product texture is unavailable', async () => {
    const { renderer } = await renderProducts({ products: [{ ...lip, texture: null }] });
    expect(textRows(renderer)).toContain('chat.selectShade'); // Ingredient selection is independent of AR support.
    expect(textRows(renderer)).not.toContain('chat.trySelectedShade');
    expect(textRows(renderer)).toContain('chat.openProduct ›');
    await act(async () => { renderer.unmount(); });
  });

  it('keeps server order across condition groups and validates controlled shade ownership', async () => {
    const second = { ...lip, id: 'lip-2', name: 'Second', category: 'skincare' as const,
      shades: [{ id: 'second-03', name: '03 Second', hex: '#123456' }] };
    const onSelectShade = jest.fn();
    const { renderer, onOpenAr } = await renderProducts({ products: [second, lip],
      candidateOrder: [second.id, lip.id], onSelectShade,
      selectedShades: { [lip.id]: 'second-03' },
    });
    const rows = textRows(renderer);
    expect(rows.indexOf('Second')).toBeLessThan(rows.indexOf('Lip product'));
    expect(rows).toContain('chat.candidateNumber:2');
    expect(rows).not.toContain('chat.trySelectedShade');
    await act(async () => { buttonWithText(renderer.root, 'Rose').props.onPress(); });
    expect(onSelectShade).toHaveBeenCalledWith(lip.id, 'shade-1');
    expect(onOpenAr).not.toHaveBeenCalled();
    await act(async () => { renderer.unmount(); });
  });
  it('opens a comparison sheet without changing candidate selection or server order', async () => {
    const onSelectProduct = jest.fn();
    const { renderer } = await renderProducts({
      products: [lip, care],
      candidateOrder: [care.id, lip.id],
      selectedProductId: lip.id,
      onSelectProduct,
    });
    expect(renderer.root.findByType(ProductCompareSheet).props.visible).toBe(false);
    await act(async () => {
      renderer.root.findByProps({ accessibilityLabel: 'chat.compare.open' }).props.onPress();
    });
    const compare = renderer.root.findByType(ProductCompareSheet);
    expect(compare.props.visible).toBe(true);
    expect(compare.props.products.map((product: Product) => product.id)).toEqual(['care-1', 'lip-1']);
    expect(compare.props.selectedProductId).toBe('lip-1');
    expect(onSelectProduct).not.toHaveBeenCalled();
    await act(async () => { compare.props.onSelectProduct('care-1'); });
    expect(onSelectProduct).toHaveBeenCalledWith('care-1');
    await act(async () => { renderer.root.findByType(ProductCompareSheet).props.onClose(); });
    expect(renderer.root.findByType(ProductCompareSheet).props.visible).toBe(false);
    await act(async () => { renderer.unmount(); });
  });

  it('renders candidates in a horizontal carousel and never selects on swipe', async () => {
    const onSelectProduct = jest.fn();
    const { renderer } = await renderProducts({
      products: [lip, care], candidateOrder: [care.id, lip.id],
      onSelectProduct, selectedProductId: null,
    });
    const carousel = renderer.root.findByProps({ testID: 'chat-products-carousel' });
    expect(carousel.type).toBe(ScrollView);
    expect(carousel.props.horizontal).toBe(true);
    expect(carousel.props.snapToInterval).toBeGreaterThan(0);
    expect(textRows(renderer)).toContain('1 / 2');
    await act(async () => {
      carousel.props.onMomentumScrollEnd({ nativeEvent: { contentOffset: { x: carousel.props.snapToInterval } } });
    });
    expect(textRows(renderer)).toContain('2 / 2');
    expect(onSelectProduct).not.toHaveBeenCalled();
    await act(async () => {
      renderer.root.findByProps({ accessibilityLabel: 'chat.carousel.choose: Care product' }).props.onPress();
    });
    expect(onSelectProduct).toHaveBeenCalledWith('care-1');
    await act(async () => { renderer.unmount(); });
  });

  it('keeps the original server candidate positions when a referenced product is missing', async () => {
    const { renderer } = await renderProducts({
      products: [lip], candidateOrder: [care.id, lip.id],
      expectedIds: [care.id, lip.id], missingCount: 1,
    });
    expect(textRows(renderer)).toContain('1 / 2');
    expect(textRows(renderer)).toContain('chat.candidateNumber:1');
    expect(textRows(renderer)).toContain('chat.candidateNumber:2');
    expect(textRows(renderer)).toContain('chat.productMissing');
    const carousel = renderer.root.findByProps({ testID: 'chat-products-carousel' });
    await act(async () => {
      carousel.props.onMomentumScrollEnd({ nativeEvent: { contentOffset: { x: carousel.props.snapToInterval } } });
    });
    expect(textRows(renderer)).toContain('2 / 2');
    await act(async () => { renderer.unmount(); });
  });

  it('does not expose explicit product selection in a disabled preview', async () => {
    const onSelectProduct = jest.fn();
    const { renderer } = await renderProducts({
      products: [lip], candidateOrder: [lip.id],
      selectedProductId: null, onSelectProduct, disabledActions: true,
    });
    const choose = renderer.root.findByProps({ accessibilityLabel: 'chat.carousel.choose: Lip product' });
    expect(choose.props.disabled).toBe(true);
    expect(choose.props.accessibilityState.disabled).toBe(true);
    expect(choose.props.onPress).toBeUndefined();
    expect(onSelectProduct).not.toHaveBeenCalled();
    await act(async () => { renderer.unmount(); });
  });

});


test('G4 displays option verdicts without reclassifying current price from product reference price', async () => {
  const { renderer } = await renderProducts({ products: [lip], optionSearch: {
    schemaVersion: 1, status: 'PARTIAL', products: [lip], excludedCount: 0, omittedCount: 0,
    checkedScope: { candidateProducts: 1, candidateOptions: 1, checkedOptions: 1, unidentifiedOptions: 0, exhaustive: true, stoppedReason: 'COMPLETE', errors: 0 },
    items: [{ productId: lip.id, shadeId: 'shade-1', optionId: 'synthetic-option', sourceVersion: 'v1', synthetic: true, group: 'REFERENCE_ONLY', checks: [
      { condition: 'identity', verdict: 'MATCH', reason: 'verified_option' },
      { condition: 'price', verdict: 'UNKNOWN', reason: 'current_price_unverified' },
      { condition: 'texture', verdict: 'UNKNOWN', reason: 'option_texture_unverified' },
      { condition: 'ingredient', ingredientName: 'Fragrance', operator: 'excludes', verdict: 'UNKNOWN', reason: 'absence_not_verifiable' },
      { condition: 'ingredient', ingredientName: 'Water', operator: 'includes', verdict: 'ERROR', reason: 'timeout' },
    ] }],
  } });
  const rows = textRows(renderer).join(' ');
  expect(rows).toContain('Rose · chat.option.reference');
  expect(rows).toContain('chat.option.price: chat.conditionUnknown');
  expect(rows).toContain('chat.option.textureUnverified');
  expect(rows).toContain('chat.option.error');
  expect(rows).not.toContain('chat.conditionMet');
  expect(rows).not.toContain('chat.ui.candidatesMatched');
  await act(async () => renderer.unmount());
});

test('G4 explains identity counts, texture source and recorded price without inventing a timezone', async () => {
  const { renderer } = await renderProducts({ products: [lip], optionSearch: {
    schemaVersion: 1, status: 'PARTIAL', products: [lip], excludedCount: 0, omittedCount: 0,
    checkedScope: { candidateProducts: 1, candidateOptions: 1, checkedOptions: 1, unidentifiedOptions: 0, exhaustive: true, stoppedReason: 'COMPLETE', errors: 0 },
    items: [{ productId: lip.id, shadeId: 'shade-1', optionId: 'option', sourceVersion: 'v1', synthetic: true,
      ingredientEntryCount: 28, ingredientIdentityCount: 27, group: 'REFERENCE_ONLY',
      checks: [{ condition: 'texture', verdict: 'UNKNOWN', reason: 'option_texture_unverified', textureBasis: 'review_survey' }],
      price: { requestedBasis: 'collected_snapshot', observedBasis: 'collected_snapshot', amountKRW: 7600,
        observedAtRaw: '2026-10-27T17:23:57', checkedAt: '2026-11-17T00:00:00Z',
        sourceRef: 'fixture://price', sourceVersion: 'p1', limitations: ['timezone_unknown'] },
    }],
  } });
  const rows = textRows(renderer).join(' ');
  expect(rows).toContain('chat.option.identities');
  expect(rows).toContain('chat.option.registeredPrice ₩15,000');
  expect(rows).toContain('chat.option.snapshot: ₩7,600');
  expect(rows).toContain('chat.option.textureReview');
  expect(rows).toContain('2026-10-27T17:23:57 · chat.option.timezoneUnknown');
  expect(rows).not.toContain('2026-10-27T17:23:57Z');
  expect(rows).not.toContain('chat.conditionMet');
  await act(async () => renderer.unmount());
});

test('G4 shows a confirmed option finish and its timezone-qualified snapshot', async () => {
  const { renderer } = await renderProducts({ products: [lip], optionSearch: {
    schemaVersion: 1, status: 'SUCCESS', products: [lip], excludedCount: 0, omittedCount: 0,
    checkedScope: { candidateProducts: 1, candidateOptions: 1, checkedOptions: 1, unidentifiedOptions: 0, exhaustive: true, stoppedReason: 'COMPLETE', errors: 0 },
    items: [{ productId: lip.id, shadeId: 'shade-1', optionId: 'option', sourceVersion: 'v1', synthetic: false,
      group: 'ELIGIBLE', checks: [{ condition: 'texture', verdict: 'MATCH', reason: 'official_option_texture_reviewed', textureBasis: 'official_reviewed' }],
      price: { requestedBasis: 'collected_snapshot', observedBasis: 'collected_snapshot', amountKRW: 12000,
        observedAt: '2026-10-27T17:59:38+09:00', checkedAt: '2026-11-18T00:00:00Z',
        sourceRef: 'fixture://price', sourceVersion: 'p1' },
    }],
  } });
  const rows = textRows(renderer).join(' ');
  expect(rows).toContain('Rose · chat.option.eligible');
  expect(rows).toContain('chat.option.textureOfficial');
  expect(rows).toContain('chat.option.texture: chat.conditionMet');
  expect(rows).toContain('2026-10-27T17:59:38+09:00');
  expect(rows).not.toContain('chat.option.timezoneUnknown');
  await act(async () => renderer.unmount());
});

test('G4 displays the registered price once and explains an unverified fragrance-free claim', async () => {
  const registeredLip = { ...lip, priceKRW: 5900 };
  const { renderer } = await renderProducts({ products: [registeredLip], optionSearch: {
    schemaVersion: 1, status: 'PARTIAL', products: [registeredLip], excludedCount: 0, omittedCount: 0,
    checkedScope: { candidateProducts: 1, candidateOptions: 1, checkedOptions: 1, unidentifiedOptions: 0, exhaustive: true, stoppedReason: 'COMPLETE', errors: 0 },
    items: [{ productId: lip.id, shadeId: 'shade-1', optionId: 'option', sourceVersion: 'v1', synthetic: false,
      group: 'REFERENCE_ONLY', checks: [
        { condition: 'fragrance_free', verdict: 'UNKNOWN', reason: 'unsupported_claim' },
        { condition: 'price', verdict: 'MATCH', reason: 'requested_price_basis' },
      ],
      price: { requestedBasis: 'catalog_reference', observedBasis: 'catalog_reference', amountKRW: 5900,
        checkedAt: '2026-11-18T00:00:00Z', sourceRef: '/api/products/lip', sourceVersion: 'p1' },
    }],
  } });
  const rows = textRows(renderer).join(' ');
  expect(rows).toContain('chat.option.registeredPrice ₩5,900');
  expect(rows.split('₩5,900')).toHaveLength(2);
  expect(rows).toContain('chat.option.fragranceUnknown');
  expect(rows).not.toContain('chat.option.snapshot');
  await act(async () => renderer.unmount());
});

test('G4 keeps the registered price and labels a fragrance-excluded shade during a current-price search', async () => {
  const product = { ...lip, priceKRW: 5900, shades: [
    ...lip.shades,
    { id: 'shade-2', name: 'Pink', hex: '#dd3399' },
    { id: 'shade-3', name: 'Plum', hex: '#990077' },
  ] };
  const reference: ChatOptionSearch['items'][number] = {
    productId: lip.id, shadeId: 'shade-1', optionId: 'option-1', sourceVersion: 'v1', synthetic: false,
    group: 'REFERENCE_ONLY', checks: [
      { condition: 'fragrance_free', verdict: 'UNKNOWN', reason: 'absence_not_verifiable' },
      { condition: 'price', verdict: 'UNKNOWN', reason: 'current_price_unverified' },
    ],
    price: { requestedBasis: 'current_offer', observedBasis: 'collected_snapshot', amountKRW: 7600,
      checkedAt: '2026-11-18T00:00:00Z', sourceRef: 'fixture://price', sourceVersion: 'p1' },
  };
  const onSelectShade = jest.fn();
  const { renderer } = await renderProducts({ products: [product], onSelectShade,
    selectedShades: { [lip.id]: 'shade-3' }, optionSearch: {
      schemaVersion: 1, status: 'PARTIAL', products: [product], excludedCount: 1, omittedCount: 0,
      checkedScope: { candidateProducts: 1, candidateOptions: 3, checkedOptions: 3, unidentifiedOptions: 0,
        exhaustive: true, stoppedReason: 'COMPLETE', errors: 0 },
      items: [reference, { ...reference, shadeId: 'shade-2', optionId: 'option-2' }, {
        ...reference, shadeId: 'shade-3', optionId: 'option-3', group: 'EXCLUDED',
        checks: [{ condition: 'fragrance_free', verdict: 'NOT_MATCH', reason: 'ingredient_present' }],
      }],
    },
  });
  const rows = textRows(renderer);
  expect(rows).toContain('chat.option.registeredPrice ₩5,900');
  expect(rows.join(' ')).not.toContain('₩7,600');
  expect(rows.filter((row) => row === 'chat.option.fragranceUnknown')).toHaveLength(1);
  expect(rows).toContain('Plum');
  expect(rows).toContain('chat.conditionNotMet');
  await act(async () => buttonWithText(renderer.root, 'Plum').props.onPress());
  expect(onSelectShade).toHaveBeenCalledWith(lip.id, 'shade-3');
  expect(rows).not.toContain('chat.option.currentPriceUnknown');
  await act(async () => buttonWithText(renderer.root, 'Rose').props.onPress());
  expect(onSelectShade).toHaveBeenCalledWith(lip.id, 'shade-1');
  await act(async () => renderer.unmount());
});

test('G4 labels each shade and preserves exact shade selection, detail and try-on', async () => {
  const product = { ...lip, shades: [
    ...lip.shades,
    { id: 'shade-2', name: 'Coral', hex: '#ee7755' },
    { id: 'shade-3', name: 'Berry', hex: '#771133' },
    { id: 'shade-4', name: 'Peach', hex: '#dda577' },
    { id: 'shade-5', name: 'Nude', hex: '#b08c75' },
  ] };
  const makeItem = (shadeId: string, group: ChatOptionSearch['items'][number]['group'],
    checks: ChatOptionSearch['items'][number]['checks']): ChatOptionSearch['items'][number] => ({
    productId: lip.id, shadeId, optionId: 'option-' + shadeId, sourceVersion: 'v1', synthetic: false, group, checks,
  });
  const onSelectShade = jest.fn();
  const { renderer, onOpenProduct, onOpenAr } = await renderProducts({
    products: [product], onSelectShade, optionSearch: {
      schemaVersion: 1, status: 'PARTIAL', products: [product], excludedCount: 2, omittedCount: 0,
      checkedScope: { candidateProducts: 1, candidateOptions: 5, checkedOptions: 4, unidentifiedOptions: 0,
        exhaustive: false, stoppedReason: 'WORK_LIMIT', errors: 0 },
      items: [
        makeItem('shade-1', 'ELIGIBLE', [{ condition: 'price', verdict: 'MATCH', reason: 'requested_price_basis' }]),
        makeItem('shade-2', 'EXCLUDED', [{ condition: 'ingredient', verdict: 'NOT_MATCH', reason: 'ingredient_present' }]),
        makeItem('shade-3', 'EXCLUDED', [{ condition: 'price', verdict: 'NOT_MATCH', reason: 'requested_price_basis' }]),
        makeItem('shade-4', 'REFERENCE_ONLY', [{ condition: 'ingredient', verdict: 'UNKNOWN', reason: 'absence_not_verifiable' }]),
      ],
    },
  });
  for (const [name, shadeId, label] of [
    ['Rose', 'shade-1', 'chat.option.eligible'],
    ['Coral', 'shade-2', 'chat.conditionNotMet'],
    ['Berry', 'shade-3', 'chat.conditionNotMet'],
    ['Peach', 'shade-4', 'chat.option.reference'],
    ['Nude', 'shade-5', 'chat.conditionUnknown'],
  ]) {
    const button = buttonWithText(renderer.root, name);
    expect(button.props.accessibilityLabel).toBe(`${lip.name}, ${name}, ${label}`);
    expect(button.findAllByType(Text).some((item) => item.props.children === label)).toBe(true);
    expect(button.props.disabled).toBe(false);
    await act(async () => button.props.onPress());
    expect(onSelectShade).toHaveBeenLastCalledWith(lip.id, shadeId);
    expect(buttonWithText(renderer.root, name).props.accessibilityState.selected).toBe(true);
    await act(async () => buttonWithText(renderer.root, 'chat.trySelectedShade').props.onPress());
    expect(onOpenAr).toHaveBeenLastCalledWith(lip.id, shadeId);
    const open = renderer.root.findAll((node) => typeof node.props.onPress === 'function'
      && node.props.accessibilityLabel === `${lip.brand} ${lip.name}, chat.openProduct`)[0];
    await act(async () => open.props.onPress());
    expect(onOpenProduct).toHaveBeenLastCalledWith(lip.id, shadeId);
  }
  await act(async () => renderer.unmount());
});
