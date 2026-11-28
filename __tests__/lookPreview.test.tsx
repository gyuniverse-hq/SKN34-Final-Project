import React from 'react';
import renderer, { act } from 'react-test-renderer';
import LookPreviewScreen from '@/app/look-preview';
import { Button } from '@/components/ui/Button';
import { ProductCard } from '@/components/ui/ProductCard';
import { buildLookPreview } from '@/lib/lookPreview';
import { useCartStore } from '@/store/cartStore';
import { useLookPreviewStore } from '@/store/lookPreviewStore';
import { useLookMakeupStore, useMakeupStore } from '@/store/makeupStore';
import type { CelebLook, Product } from '@/types';

const mockReplace = jest.fn();
const mockPush = jest.fn();
let mockId = 'test-look';
jest.mock('expo-router', () => ({
  Stack: { Screen: () => null },
  useLocalSearchParams: () => ({ id: mockId }),
  useRouter: () => ({ replace: mockReplace, push: mockPush }),
}));
jest.mock('react-native-safe-area-context', () => ({ SafeAreaView: 'SafeAreaView' }));
jest.mock('@/components/look/LookColorMap', () => ({
  LookColorMap: (props: { onZonePress?: (zone: string) => void }) => {
    const ReactLib = require('react');
    return ReactLib.createElement('LookColorMap', props);
  },
}));
jest.mock('@/components/ui/ProductCard', () => ({ ProductCard: 'ProductCard' }));
jest.mock('@/lib/i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }));

const blush: Product = {
  id: 'blush', brand: 'Brand', name: 'Cheek Color', nameKo: 'Cheek Color', category: 'cheek', makeupZone: 'blush',
  shades: [{ id: 'peach', name: 'Peach', hex: '#FF9977' }], texture: 'matte',
  priceKRW: 0, volume: '', description: '', keyIngredients: [], tags: [], imageUrl: '', searchKeyword: '',
};
const look: CelebLook = {
  id: 'test-look', title: 'Peach Look', inspiration: '', description: '', thumbnailUrl: '', tutorialQuery: '', tags: [],
  items: [{ productId: blush.id, shadeId: 'peach', step: 'cheeks' }],
  makeup: { lip: null, eyeshadow: null, blush: { hex: '#AA4455', intensity: 0.6, texture: 'matte' } },
};

beforeEach(() => {
  jest.useFakeTimers();
  mockReplace.mockClear();
  mockPush.mockClear();
  mockId = look.id;
  useLookMakeupStore.getState().reset();
  useMakeupStore.getState().reset();
  useCartStore.getState().reset();
  useLookPreviewStore.setState({ draft: { look, products: [blush], video: true } });
});

afterEach(() => jest.useRealTimers());

test('shows the layer color and its exact product and shade', () => {
  expect(buildLookPreview(look, [blush], true)).toMatchObject([
    { zone: 'blush', hex: '#AA4455', product: { product: blush, shade: blush.shades[0] } },
  ]);
  expect(buildLookPreview({ ...look, makeup: { ...look.makeup, blush: null } }, [blush], true)).toEqual([]);
});

test('all face map numbers have space between their marker circles', () => {
  const { LOOK_MAP_MARKERS } = jest.requireActual<typeof import('@/components/look/LookColorMap')>('@/components/look/LookColorMap');
  const markers = Object.values(LOOK_MAP_MARKERS);
  expect(markers).toHaveLength(9);
  for (const [index, first] of markers.entries()) {
    for (const second of markers.slice(index + 1)) {
      expect(Math.hypot(first.x - second.x, first.y - second.y)).toBeGreaterThan(24);
    }
  }
});

test('waiting and leaving the confirmation never enter AR or apply makeup', async () => {
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<LookPreviewScreen />); });
  await act(async () => { jest.advanceTimersByTime(10000); });
  await act(async () => { screen.unmount(); });
  expect(mockReplace).not.toHaveBeenCalled();
  expect(useLookMakeupStore.getState().activeLook).toBeNull();
});

test.each([true, false])('Start applies the look once without changing product makeup (video=%s)', async (video) => {
  useLookPreviewStore.setState({ draft: { look, products: [blush], video } });
  useMakeupStore.getState().applyShade(blush, { id: 'rose', name: 'Rose', hex: '#DD4455' });
  const originalProductMakeup = useMakeupStore.getState().makeup;
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<LookPreviewScreen />); });
  const start = screen.root.findAllByType(Button).find(({ props }) => props.label === 'lookPreview.start')!;
  await act(async () => { start.props.onPress(); start.props.onPress(); });
  expect(mockReplace).toHaveBeenCalledTimes(1);
  expect(mockReplace).toHaveBeenCalledWith({
    pathname: '/ar', params: video ? { video: '1' } : { look: '1', compare: '1' },
  });
  expect(useMakeupStore.getState().makeup).toBe(originalProductMakeup);
  expect(useMakeupStore.getState().activeLook).toBeNull();
  expect(useLookMakeupStore.getState().makeup.blush?.hex).toBe('#AA4455');
  useLookMakeupStore.getState().setIntensity('blush', 0.3);
  useMakeupStore.getState().reset();
  expect(useLookMakeupStore.getState().makeup.blush?.intensity).toBe(0.3);
  await act(async () => { screen.unmount(); });
});

test('product opens detail and add-to-cart stays on the confirmation page', async () => {
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<LookPreviewScreen />); });
  const card = screen.root.findByType(ProductCard);
  expect(card.props.selectedShade).toEqual(blush.shades[0]);
  await act(async () => { card.props.onPress(); });
  expect(mockPush).toHaveBeenLastCalledWith({
    pathname: '/product/[id]', params: { id: 'blush', shade: 'peach', requireShade: '1' },
  });
  const add = screen.root.findAllByType(Button).find(({ props }) => props.label === 'lookPreview.addToCart')!;
  await act(async () => { add.props.onPress(); });
  expect(useCartStore.getState().items).toEqual([{ productId: 'blush', shadeId: 'peach', quantity: 1 }]);
  expect(JSON.stringify(screen.toJSON())).toContain('product.added');
  expect(JSON.stringify(screen.toJSON())).toContain('looks.viewCart');
  expect(mockReplace).not.toHaveBeenCalled();
  await act(async () => {
    screen.root.findAllByProps({ accessibilityLabel: 'looks.viewCart' })[0].props.onPress();
  });
  expect(mockPush).toHaveBeenLastCalledWith('/cart');
  await act(async () => { screen.unmount(); });
});

test('face map numbers jump to the matching zone products', async () => {
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<LookPreviewScreen />); });
  const map = screen.root.findByProps({ caption: 'lookPreview.mapCaption' });
  expect(typeof map.props.onZonePress).toBe('function');
  await act(async () => { map.props.onZonePress('blush'); });
  expect(JSON.stringify(screen.toJSON())).toContain('lookPreview.arColor');
  expect(JSON.stringify(screen.toJSON())).toContain('lookPreview.productShade');
  await act(async () => { screen.unmount(); });
});

test('an unmapped look color has no product or cart button', async () => {
  useLookPreviewStore.setState({ draft: { look, products: [], video: true } });
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<LookPreviewScreen />); });
  expect(screen.root.findAllByType(ProductCard)).toHaveLength(0);
  expect(screen.root.findByType(Button).props.label).toBe('lookPreview.start');
  await act(async () => { screen.unmount(); });
});

test('a stale confirmation URL cannot start another look', async () => {
  mockId = 'another-look';
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<LookPreviewScreen />); });
  const start = screen.root.findByType(Button);
  expect(start.props.disabled).toBe(true);
  await act(async () => { start.props.onPress(); });
  expect(mockReplace).not.toHaveBeenCalled();
  await act(async () => { screen.unmount(); });
});
