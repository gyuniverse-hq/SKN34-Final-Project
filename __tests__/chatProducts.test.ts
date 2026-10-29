import { createElement } from 'react';
import { Text } from 'react-native';
import { act, create, type ReactTestInstance, type ReactTestRenderer } from 'react-test-renderer';
import { ChatProducts } from '@/components/chat/ChatProducts';
import { ProductImage } from '@/components/ui/ProductImage';
import type { ChatCondition } from '@/lib/chatConditions';
import type { Product } from '@/types';

jest.mock('@/lib/i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }));
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
  it('shows catalog data and compares explicit conditions without inferring fragrance safety', async () => {
    const { renderer } = await renderProducts();
    const rows = textRows(renderer);
    expect(rows).toContain('Lip product');
    expect(rows).toContain('chat.referencePrice ₩15,000');
    expect(rows).toContain('shop.cat.lip');
    expect(rows).toContain('product.keyIngredients: Panthenol');
    expect(rows).toContain('chat.ui.keyIngredientsNotice');
    expect(rows).toContain('lip · chat.conditionMet');
    expect(rows).toContain('lip · chat.conditionNotMet');
    expect(rows).toContain('under 20000 · chat.conditionMet (chat.conditionPriceBasis)');
    expect(rows).toContain('under 20000 · chat.conditionNotMet (chat.conditionPriceBasis)');
    expect(rows.filter((row) => row === 'fragrance-free · chat.conditionUnknown')).toHaveLength(2);
    expect(renderer.root.findAllByType(ProductImage).map((node) => node.props.uri))
      .toEqual(['https://example.com/lip.jpg', 'https://example.com/care.jpg']);
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

  it('does not offer AR when a product id or its shade id is invalid', async () => {
    const badProduct = { ...lip, id: '../bad' };
    const badShade = { ...lip, id: 'lip-2', shades: [{ id: '../bad', name: 'Invalid shade', hex: '#000000' }] };
    const { renderer } = await renderProducts({ products: [badProduct, badShade] });
    expect(textRows(renderer)).not.toContain('chat.trySelectedShade');
    expect(textRows(renderer)).not.toContain('chat.selectShade');
    await act(async () => { renderer.unmount(); });
  });
});
