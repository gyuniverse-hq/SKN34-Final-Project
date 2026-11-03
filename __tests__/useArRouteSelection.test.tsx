import React, { useEffect } from 'react';
import renderer, { act } from 'react-test-renderer';
import ProductDetailScreen from '@/app/product/[id]';
import { Button } from '@/components/ui/Button';
import { ShadePicker } from '@/components/ui/ShadePicker';
import { useArRouteSelection } from '@/hooks/useArRouteSelection';
import type { Product } from '@/types';

const mockApplyShade = jest.fn();
const mockPush = jest.fn();
const mockNotify = jest.fn();
let mockRouteParams: { id: string; shade?: string } = { id: 'product-1' };
const mockProduct: Product = {
  id: 'product-1', brand: 'Brand', name: 'Lip', nameKo: '립', category: 'lip',
  makeupZone: 'lip', texture: 'matte', priceKRW: 10000, volume: '1',
  shades: [{ id: '01', name: '01', hex: '#112233' }, { id: '03', name: '03', hex: '#445566' }],
  description: '', keyIngredients: [], tags: [], imageUrl: '', searchKeyword: '',
};
let mockCurrentProduct = mockProduct;
jest.mock('@/lib/queries', () => ({ useProduct: () => ({ data: mockCurrentProduct }) }));
jest.mock('@/components/ui/StateViews', () => ({ EmptyState: 'EmptyState', ErrorState: 'ErrorState', LoadingState: 'LoadingState' }));
jest.mock('@/components/ui/ProductImage', () => ({ ProductImage: 'ProductImage' }));
jest.mock('@/components/ui/Button', () => ({ Button: () => null }));
jest.mock('@/components/ui/ShadePicker', () => ({ ShadePicker: () => null }));
jest.mock('@/store/cartStore', () => ({ useCartStore: (selector: (state: unknown) => unknown) => selector({ add: jest.fn() }) }));
jest.mock('@/store/compareStore', () => ({ MAX_COMPARE: 3, useCompareStore: (selector: (state: unknown) => unknown) => selector({ add: jest.fn(), items: [] }) }));
jest.mock('@/store/makeupStore', () => ({ useMakeupStore: (selector: (state: unknown) => unknown) => selector({ applyShade: mockApplyShade }) }));
jest.mock('@/lib/confirm', () => ({ notify: (...args: unknown[]) => mockNotify(...args) }));
jest.mock('@/lib/i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }));
jest.mock('@expo/vector-icons/Ionicons', () => 'Ionicons');
jest.mock('react-native-safe-area-context', () => ({ SafeAreaView: 'SafeAreaView' }));
jest.mock('expo-router', () => ({
  Stack: { Screen: () => null },
  useLocalSearchParams: () => mockRouteParams,
  useRouter: () => ({ push: mockPush, setParams: jest.fn() }),
}));

let selection: ReturnType<typeof useArRouteSelection>;
function Subject({ shadeId }: { shadeId?: string }) {
  const result = useArRouteSelection('product-1', shadeId);
  useEffect(() => { selection = result; }, [result]);
  return null;
}

beforeEach(() => { mockApplyShade.mockClear(); mockPush.mockClear(); mockNotify.mockClear(); mockRouteParams = { id: 'product-1' }; mockCurrentProduct = mockProduct; });

it.each([undefined, 'other-product-shade'])('does not apply an unselected or invalid shade %s', async (shadeId) => {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<Subject shadeId={shadeId} />); });
  expect(mockApplyShade).not.toHaveBeenCalled();
  expect(selection.shade).toBeUndefined();
  expect(selection.shadeMissing).toBe(true);
  await act(async () => { tree.unmount(); });
});

it('applies the requested shade belonging to the product', async () => {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<Subject shadeId="03" />); });
  expect(mockApplyShade).toHaveBeenCalledTimes(1);
  expect(mockApplyShade).toHaveBeenCalledWith(mockProduct, mockProduct.shades[1]);
  expect(selection.shadeMissing).toBe(false);
  await act(async () => { tree.update(<Subject shadeId="03" />); });
  expect(mockApplyShade).toHaveBeenCalledTimes(1);
  await act(async () => { tree.unmount(); });
});

it.each([{ shade: '03', valid: true }, { shade: 'wrong', valid: false }])('checks an incoming product detail shade $shade before AR', ({ shade, valid }) => {
  mockRouteParams = { id: 'product-1', shade };
  let tree!: renderer.ReactTestRenderer;
  act(() => { tree = renderer.create(<ProductDetailScreen />); });
  const button = tree.root.findAllByType(Button).find((item) => item.props.label === 'product.tryInAr')!;
  act(() => { button.props.onPress(); });
  if (valid) expect(mockPush).toHaveBeenCalledWith(expect.objectContaining({ params: expect.objectContaining({ productId: 'product-1', shadeId: '03' }) }));
  else { expect(mockPush).not.toHaveBeenCalled(); expect(mockNotify).toHaveBeenCalled(); }
  act(() => { tree.unmount(); });
});

it('does not reuse an earlier product selection when the next product has the same shade ID', () => {
  let tree!: renderer.ReactTestRenderer;
  act(() => { tree = renderer.create(<ProductDetailScreen />); });
  act(() => { tree.root.findByType(ShadePicker).props.onSelect(mockProduct.shades[1]); });
  mockRouteParams = { id: 'product-2' };
  mockCurrentProduct = { ...mockProduct, id: 'product-2' };
  act(() => { tree.update(<ProductDetailScreen />); });
  const button = tree.root.findAllByType(Button).find((item) => item.props.label === 'product.tryInAr')!;
  act(() => { button.props.onPress(); });
  expect(mockPush).not.toHaveBeenCalled();
  expect(mockNotify).toHaveBeenCalled();
  act(() => { tree.unmount(); });
});

it.each([{ shade: '03', allowed: false }, { shade: '01', allowed: true }])(
  'handles shade $shade when a mounted product screen changes to another product',
  ({ shade, allowed }) => {
    let tree!: renderer.ReactTestRenderer;
    act(() => { tree = renderer.create(<ProductDetailScreen />); });
    act(() => { tree.root.findByType(ShadePicker).props.onSelect(mockProduct.shades[1]); });
    mockRouteParams = { id: 'product-2', shade };
    mockCurrentProduct = { ...mockProduct, id: 'product-2' };
    act(() => { tree.update(<ProductDetailScreen />); });
    const button = tree.root.findAllByType(Button).find((item) => item.props.label === 'product.tryInAr')!;
    act(() => { button.props.onPress(); });
    if (allowed) expect(mockPush).toHaveBeenCalledWith(expect.objectContaining({ params: expect.objectContaining({ productId: 'product-2', shadeId: shade }) }));
    else { expect(mockPush).not.toHaveBeenCalled(); expect(mockNotify).toHaveBeenCalled(); }
    act(() => { tree.unmount(); });
  }
);

it('keeps the default shade visible but requires an explicit selection before product AR', () => {
  let tree!: renderer.ReactTestRenderer;
  act(() => { tree = renderer.create(<ProductDetailScreen />); });
  expect(tree.root.findByType(ShadePicker).props.selectedId).toBe('01');
  const arButton = () => tree.root.findAllByType(Button).find((button) => button.props.label === 'product.tryInAr')!;
  act(() => { arButton().props.onPress(); });
  expect(mockPush).not.toHaveBeenCalled();
  expect(mockNotify).toHaveBeenCalled();
  act(() => { tree.root.findByType(ShadePicker).props.onSelect(mockProduct.shades[1]); });
  act(() => { arButton().props.onPress(); });
  expect(mockPush).toHaveBeenCalledWith(expect.objectContaining({ params: expect.objectContaining({ productId: 'product-1', shadeId: '03' }) }));
  act(() => { tree.unmount(); });
});
