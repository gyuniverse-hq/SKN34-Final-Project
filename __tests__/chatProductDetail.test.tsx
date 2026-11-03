import { createElement } from 'react';
import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import ProductDetail from '@/app/product/[id]';
import { Button } from '@/components/ui/Button';
import { ShadePicker } from '@/components/ui/ShadePicker';
import { productHref } from '@/lib/routes';
import { useCartStore } from '@/store/cartStore';
import type { Product } from '@/types';

const mockProduct = { id: 'lip', brand: 'Fixture', name: 'Test lip', nameKo: '', category: 'lip',
  makeupZone: 'lip', texture: 'matte', priceKRW: 10000, volume: '', description: '', keyIngredients: [],
  tags: [], imageUrl: '', searchKeyword: '', shades: [
    { id: 'first', name: 'First', hex: '#112233' }, { id: 'selected', name: 'Selected', hex: '#445566' },
  ] } as Product;
const mockHref = productHref(mockProduct.id, 'selected');
const mockRoute = typeof mockHref === 'object' ? mockHref.params : {};
jest.mock('expo-router', () => ({ Stack: { Screen: () => null },
  useLocalSearchParams: () => mockRoute, useRouter: () => ({ push: jest.fn(), setParams: jest.fn() }),
}));
jest.mock('@/lib/queries', () => ({ useProduct: () => ({ data: mockProduct, isPending: false, isError: false }) }));
jest.mock('@/lib/i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }));
jest.mock('react-native-safe-area-context', () => ({ SafeAreaView: ({ children }: { children: unknown }) => children }));
jest.mock('@/components/ui/ProductImage', () => ({ ProductImage: () => null }));
jest.mock('@/components/ui/StateViews', () => ({ EmptyState: () => null, ErrorState: () => null, LoadingState: () => null }));
jest.mock('@expo/vector-icons/Ionicons', () => () => null);
jest.mock('expo-haptics', () => ({ notificationAsync: async () => {}, NotificationFeedbackType: { Success: 'success' } }));

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
