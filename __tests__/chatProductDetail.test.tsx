import { createElement } from 'react';
import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import ProductDetail from '@/app/product/[id]';
import { Button } from '@/components/ui/Button';
import { ShadePicker } from '@/components/ui/ShadePicker';
import { productHref } from '@/lib/routes';
import { useCartStore } from '@/store/cartStore';
import type { Product, ProductOption } from '@/types';

const mockProduct = { id: 'lip', brand: 'Fixture', name: 'Test lip', nameKo: '', category: 'lip',
  makeupZone: 'lip', texture: 'matte', priceKRW: 10000, volume: '', description: '', keyIngredients: [],
  tags: [], imageUrl: '', searchKeyword: '', shades: [
    { id: 'first', name: 'First', hex: '#112233' }, { id: 'selected', name: 'Selected', hex: '#445566' },
  ] } as Product;
const mockHref = productHref(mockProduct.id, 'selected');
const mockRoute = (typeof mockHref === 'object' ? mockHref.params : {}) as { id?: string; shade?: string; requireShade?: string; optionId?: string };
const mockNotify = jest.fn();
jest.mock('expo-router', () => ({ Stack: { Screen: () => null },
  useLocalSearchParams: () => mockRoute, useRouter: () => ({ push: jest.fn(), setParams: jest.fn() }),
}));
let mockSale: ProductOption | undefined;
jest.mock('@/lib/queries', () => ({ useProductOption: () => ({ data: mockSale, isPending: false, isError: false }), useProduct: () => ({ data: mockProduct, isPending: false, isError: false }), useProductVideos: () => ({ data: [] }) }));
jest.mock('@/lib/i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }));
jest.mock('react-native-safe-area-context', () => ({ SafeAreaView: ({ children }: { children: unknown }) => children }));
jest.mock('@/components/ui/ProductImage', () => ({ ProductImage: () => null }));
jest.mock('@/components/ui/StateViews', () => ({ EmptyState: () => null, ErrorState: () => null, LoadingState: () => null }));
jest.mock('@expo/vector-icons/Ionicons', () => () => null);
jest.mock('expo-haptics', () => ({ notificationAsync: async () => {}, NotificationFeedbackType: { Success: 'success' } }));
jest.mock('@/lib/confirm', () => ({ notify: (...args: unknown[]) => mockNotify(...args) }));

it('keeps the chat-selected non-first shade through product details and the real cart store', async () => {
  useCartStore.getState().reset();
  let view!: ReactTestRenderer;
  await act(async () => { view = create(createElement(ProductDetail)); });
  expect(view.root.findByType(ShadePicker).props.selectedId).toBe('selected');
  await act(async () => { view.root.findAllByType(Button).find((button) => button.props.label === 'product.addToCart')!.props.onPress(); });
  expect(useCartStore.getState().items).toEqual([{ productId: 'lip', shadeId: 'selected', quantity: 1 }]);
  await act(async () => { view.unmount(); });
  useCartStore.getState().reset();
});

it('does not select or add a shade when a video product has no linked shade', async () => {
  useCartStore.getState().reset();
  mockRoute.requireShade = '1';
  delete mockRoute.shade;
  let view!: ReactTestRenderer;
  await act(async () => { view = create(createElement(ProductDetail)); });
  expect(view.root.findByType(ShadePicker).props.selectedId).toBeUndefined();
  await act(async () => { view.root.findAllByType(Button).find((button) => button.props.label === 'product.addToCart')!.props.onPress(); });
  expect(useCartStore.getState().items).toEqual([]);
  expect(mockNotify).toHaveBeenCalledWith('chat.ingredient.selection');
  await act(async () => { view.root.findByType(ShadePicker).props.onSelect(mockProduct.shades[1]); });
  expect(view.root.findByType(ShadePicker).props.selectedId).toBe('selected');
  await act(async () => { view.root.findAllByType(Button).find((button) => button.props.label === 'product.addToCart')!.props.onPress(); });
  expect(useCartStore.getState().items).toEqual([{ productId: 'lip', shadeId: 'selected', quantity: 1 }]);
  await act(async () => { view.unmount(); });
  delete mockRoute.requireShade;
  mockRoute.shade = 'selected';
  useCartStore.getState().reset();
});


it('preserves sale option through detail and cart, ignoring an unrelated route shade', async () => {
  useCartStore.getState().reset();
  mockRoute.optionId = 'sale-02';
  mockRoute.shade = 'first';
  mockSale = { productId: 'lip', optionId: 'sale-02', name: 'Sale 02', priceKRW: null,
    priceBasis: 'collected_snapshot', observedAt: null, sourceUrl: null, image: null, arShadeId: null };
  let view!: ReactTestRenderer;
  await act(async () => { view = create(createElement(ProductDetail)); });
  expect(view.root.findAllByType(ShadePicker)).toHaveLength(0);
  expect(view.root.findAllByType(Button).some(b => b.props.label === 'product.tryInAr')).toBe(false);
  expect(JSON.stringify(view.toJSON())).toContain('sale.priceUnknown');
  await act(async () => { view.root.findAllByType(Button).find(b => b.props.label === 'product.addToCart')!.props.onPress(); });
  expect(useCartStore.getState().items).toEqual([{ productId: 'lip', optionId: 'sale-02', quantity: 1 }]);
  await act(async () => { view.unmount(); });
  delete mockRoute.optionId;
  mockRoute.shade = 'selected';
  mockSale = undefined;
  useCartStore.getState().reset();
});

it('does not fall back to a product purchase for an unresolvable sale option', async () => {
  mockRoute.optionId = 'gone';
  mockSale = undefined;
  let view!: ReactTestRenderer;
  await act(async () => { view = create(createElement(ProductDetail)); });
  expect(view.root.findAllByType(Button)).toHaveLength(0);
  await act(async () => { view.unmount(); });
  delete mockRoute.optionId;
});
