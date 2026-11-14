import React from 'react';
import renderer, { act } from 'react-test-renderer';
import ArTryOnScreen from '@/app/(tabs)/ar';
import { Button } from '@/components/ui/Button';
import { findColorGaps } from '@/lib/colorGaps';
import { useCartStore } from '@/store/cartStore';
import { useMakeupStore } from '@/store/makeupStore';
import type { CelebLook, Product } from '@/types';

const lip: Product = {
  id: 'oy-lip',
  brand: 'Brand',
  name: 'Lip',
  nameKo: '립',
  category: 'lip',
  makeupZone: 'lip',
  texture: 'matte',
  priceKRW: 12000,
  volume: '1',
  shades: [{ id: 's1', name: 'Red', hex: '#B3202E' }],
  description: '',
  keyIngredients: [],
  tags: [],
  imageUrl: '',
  searchKeyword: 'lip',
};

const nearby: Product = {
  ...lip,
  id: 'oy-shadow',
  name: 'Shadow',
  nameKo: '섀도',
  category: 'eye',
  makeupZone: 'eyeshadow',
  shades: [{ id: 'e1', name: 'Brown', hex: '#8A5A44' }],
};

const look = {
  id: 'look',
  title: 'Look',
  items: [
    { productId: lip.id, shadeId: 's1', step: 'lips' },
    { productId: 'missing-shadow', shadeId: 'e1', step: 'eyes' },
  ],
  makeup: {
    lip: { hex: '#B3202E', intensity: 0.8, texture: 'matte' },
    eyeshadow: { hex: '#8A5A44', intensity: 0.5, texture: 'matte' },
  },
} as unknown as CelebLook;

let mockRouteParams: { video?: string } = {};
jest.mock('react-native-safe-area-context', () => {
  const actual = jest.requireActual('react-native-safe-area-context') as typeof import('react-native-safe-area-context');
  return { ...actual, useSafeAreaInsets: () => ({ top: 0, right: 0, bottom: 0, left: 0 }) };
});
jest.mock('@expo/vector-icons/Ionicons', () => 'Ionicons');
jest.mock('expo-camera', () => ({ useCameraPermissions: () => [{ granted: false, canAskAgain: true }, jest.fn()] }));
jest.mock('expo-haptics', () => ({ notificationAsync: jest.fn(() => Promise.resolve()), NotificationFeedbackType: { Success: 'success' } }));
jest.mock('expo-router', () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), canGoBack: () => false }),
  useLocalSearchParams: () => mockRouteParams,
  useNavigation: () => ({ setOptions: jest.fn() }),
  useFocusEffect: jest.fn(),
}));
jest.mock('expo-linear-gradient', () => ({ LinearGradient: 'LinearGradient' }));
jest.mock('@/components/ar/ArFaceView', () => ({ ArFaceView: 'ArFaceView' }));
jest.mock('@/lib/i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }));
jest.mock('@/hooks/useArRouteSelection', () => ({ useArRouteSelection: () => ({ product: {} }) }));
jest.mock('@/lib/queries', () => {
  const lipProduct = {
    id: 'oy-lip',
    brand: 'Brand',
    name: 'Lip',
    nameKo: '립',
    category: 'lip',
    makeupZone: 'lip',
    texture: 'matte',
    priceKRW: 12000,
    volume: '1',
    shades: [{ id: 's1', name: 'Red', hex: '#B3202E' }],
    description: '',
    keyIngredients: [],
    tags: [],
    imageUrl: '',
    searchKeyword: 'lip',
  };
  const shadowProduct = {
    ...lipProduct,
    id: 'oy-shadow',
    name: 'Shadow',
    nameKo: '섀도',
    category: 'eye',
    makeupZone: 'eyeshadow',
    shades: [{ id: 'e1', name: 'Brown', hex: '#8A5A44' }],
  };
  return {
    useProducts: () => ({ data: [lipProduct, shadowProduct] }),
    useTryOnProducts: () => ({ data: [lipProduct, shadowProduct] }),
  };
});

it('adds only explicitly selected products even when other look colors have nearby products', async () => {
  mockRouteParams = {};
  useCartStore.setState({ items: [], pendingPayment: null });
  useMakeupStore.getState().reset();
  useMakeupStore.getState().applyLook(look, [lip]);
  const selected = Object.values(useMakeupStore.getState().selections).filter(Boolean);
  expect(selected).toHaveLength(1);
  const chosenShade = lip.shades.find((shade) => shade.id === selected[0]!.shadeId)!;
  expect(findColorGaps(look.makeup, [{ product: lip, shade: chosenShade }], [lip, nearby]).some((gap) => gap.kind === 'nearest')).toBe(true);
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<ArTryOnScreen />); });
  await act(async () => { screen.root.findByProps({ accessibilityLabel: 'ar.arc.tools' }).props.onPress(); });
  const add = screen.root.findAllByType(Button).find((button) => button.props.label === 'ar.addSelection');
  expect(add?.props.disabled).toBe(false);
  await act(async () => { add!.props.onPress(); });
  expect(useCartStore.getState().items.map((item) => item.productId)).toEqual([lip.id]);
  await act(async () => { screen.unmount(); });
});

it('does not seed an unrelated lip color when opening AR from a video', async () => {
  mockRouteParams = { video: '1' };
  useMakeupStore.getState().reset();
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<ArTryOnScreen />); });
  expect(useMakeupStore.getState().makeup.lip).toBeNull();
  await act(async () => { screen.unmount(); });
  mockRouteParams = {};
});


it('adds only the current arc shade without adding other applied zones', async () => {
  mockRouteParams = {};
  useCartStore.setState({ items: [], pendingPayment: null });
  useMakeupStore.getState().reset();
  useMakeupStore.getState().applyShade(lip, lip.shades[0]);
  useMakeupStore.getState().applyShade(nearby, nearby.shades[0]);
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<ArTryOnScreen />); });
  await act(async () => { screen.root.findByProps({ accessibilityLabel: 'ar.addThisProduct' }).props.onPress(); });
  expect(useCartStore.getState().items).toEqual([{ productId: lip.id, shadeId: 's1', quantity: 1 }]);
  expect(useMakeupStore.getState().selections.eyeshadow?.productId).toBe(nearby.id);
  await act(async () => { screen.unmount(); });
});
