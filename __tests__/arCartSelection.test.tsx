import React from 'react';
import renderer, { act } from 'react-test-renderer';
import ArTryOnScreen from '@/app/(tabs)/ar';
import { Button } from '@/components/ui/Button';
import { DEMO_LOOKS, DEMO_PRODUCTS } from '@/lib/devCatalog/demo';
import { findColorGaps } from '@/lib/colorGaps';
import { useCartStore } from '@/store/cartStore';
import { useMakeupStore } from '@/store/makeupStore';

jest.mock('@expo/vector-icons/Ionicons', () => 'Ionicons');
jest.mock('expo-camera', () => ({ useCameraPermissions: () => [{ granted: false, canAskAgain: true }, jest.fn()] }));
jest.mock('expo-haptics', () => ({ notificationAsync: jest.fn(() => Promise.resolve()), NotificationFeedbackType: { Success: 'success' } }));
jest.mock('expo-router', () => ({ useRouter: () => ({ push: jest.fn(), canGoBack: () => false }), useLocalSearchParams: () => ({}), useFocusEffect: jest.fn() }));
jest.mock('expo-linear-gradient', () => ({ LinearGradient: 'LinearGradient' }));
jest.mock('@/components/ar/ArFaceView', () => ({ ArFaceView: 'ArFaceView' }));
jest.mock('@/lib/i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }));
jest.mock('@/hooks/useArRouteSelection', () => ({ useArRouteSelection: () => ({ product: {} }) }));
jest.mock('@/lib/queries', () => ({ useProducts: () => ({ data: require('@/lib/devCatalog/demo').DEMO_PRODUCTS }) }));

it('adds only explicitly selected products even when other look colors have nearby products', async () => {
  useCartStore.setState({ items: [], pendingPayment: null });
  useMakeupStore.getState().reset();
  const look = DEMO_LOOKS.find((item) => item.items.length > 1)!;
  const chosen = DEMO_PRODUCTS.find((product) => product.id === look.items[0].productId)!;
  useMakeupStore.getState().applyLook(look, [chosen]);
  const selected = Object.values(useMakeupStore.getState().selections).filter(Boolean);
  expect(selected).toHaveLength(1);
  const chosenShade = chosen.shades.find((shade) => shade.id === selected[0]!.shadeId)!;
  expect(findColorGaps(look.makeup, [{ product: chosen, shade: chosenShade }], DEMO_PRODUCTS).some((gap) => gap.kind === 'nearest')).toBe(true);
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<ArTryOnScreen />); });
  const add = screen.root.findAllByType(Button).find((button) => button.props.label === 'ar.addSelection');
  expect(add?.props.disabled).toBe(false);
  await act(async () => { add!.props.onPress(); });
  expect(useCartStore.getState().items.map((item) => item.productId)).toEqual([chosen.id]);
  await act(async () => { screen.unmount(); });
});
