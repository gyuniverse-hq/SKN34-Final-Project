import { createElement } from 'react';
import { Text, View } from 'react-native';
import { act, create, type ReactTestInstance, type ReactTestRenderer } from 'react-test-renderer';
import { ChatProducts } from '@/components/chat/ChatProducts';
import { ProductImage } from '@/components/ui/ProductImage';
import type { ChatCondition } from '@/lib/chatConditions';
import type { Product } from '@/types';

jest.mock('@/lib/i18n', () => ({ useI18n: () => ({
  t: (key: string, params?: { index?: number }) => key === 'chat.candidateNumber' ? `${key}:${params?.index}` : key,
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
  it('shows original candidate numbering and explicitly partial ingredient evidence', async () => {
    const { renderer } = await renderProducts({ products: [lip], candidateOrder: ['another', lip.id],
      evidence: [{ productId: lip.id, source: 'catalog_api', ingredientCoverage: 'key_only', fragranceStatus: 'unknown' }] });
    const rows = textRows(renderer);
    expect(rows).toContain('chat.candidateNumber:2');
    expect(rows).toContain('chat.catalogEvidence');
    expect(rows).toContain('chat.keyOnlyEvidence');
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
    expect(onOpenProduct).toHaveBeenCalledWith('care-1');
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
});
