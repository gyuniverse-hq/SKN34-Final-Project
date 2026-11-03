import React from 'react';
import { Text } from 'react-native';
import renderer, { act } from 'react-test-renderer';
import StyleLookDetail from '@/app/style-look/[id]';
import { openYoutubeVideo } from '@/components/celeb/VideoCard';

import type { Product, StyleLookProduct } from '@/types';

const mockPush = jest.fn();
const mockOpen = jest.fn();
let mockCatalog: Product[] = [];
let mockItems: StyleLookProduct[] | undefined;

beforeEach(() => { mockCatalog = []; mockItems = undefined; mockPush.mockClear(); mockOpen.mockClear(); });

jest.mock('expo-router', () => ({
  Stack: { Screen: () => null },
  useLocalSearchParams: () => ({ id: 'video-1' }),
  useRouter: () => ({ push: mockPush, back: jest.fn(), canGoBack: () => false }),
}));
jest.mock('@expo/vector-icons/Ionicons', () => 'Ionicons');
jest.mock('expo-linear-gradient', () => ({ LinearGradient: 'LinearGradient' }));
jest.mock('@/components/celeb/VideoCard', () => ({ openYoutubeVideo: jest.fn(() => Promise.resolve()) }));
jest.mock('@/components/celeb/YoutubePlayer', () => ({ YoutubePlayer: 'YoutubePlayer' }));
jest.mock('@/hooks/useVideoTryOn', () => ({ useVideoTryOn: () => ({ open: mockOpen, loading: false, error: false, count: 0, selectedIndices: new Set() }) }));
jest.mock('@/components/ui/StateViews', () => ({ EmptyState: 'EmptyState', ErrorState: 'ErrorState', LoadingState: 'LoadingState' }));
jest.mock('@/lib/i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }));
jest.mock('@/lib/queries', () => ({
  useProducts: () => ({ data: mockCatalog }),
  useStyleLooks: () => ({ isPending: false, isError: false, data: [{
    id: 'video-1', title: 'Example look', tag: '#look', group: '컬러·톤 스타일',
    products: mockItems ?? [
      { number: 1, brand: 'A', name: 'Lip', option: '원문에 명시 정보 없음', zone: '립' },
      { number: 2, brand: 'B', name: 'Shadow', option: '02', zone: '아이섀도' },
      { number: 3, brand: 'C', name: 'Lip 2', option: '03', zone: '립' },
    ],
  }] }),
}));

test('groups products by area, marks unknown shades and opens the linked video', async () => {
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<StyleLookDetail />); });
  const text = screen.root.findAllByType(Text).map((node) => node.props.children);
  expect(text.filter((value) => value === 'styleLooks.zone.lip')).toHaveLength(1);
  expect(text).toContain('styleLooks.zone.shadow');
  expect(text).toContain('styleLooks.optionUnknown');
  expect(text).toContain('styleLooks.unverified');
  expect(screen.root.findByProps({ videoId: 'video-1', title: 'Example look' })).toBeTruthy();
  const video = screen.root.findByProps({ accessibilityRole: 'link' });
  await act(async () => { video.props.onPress(); });
  expect(openYoutubeVideo).toHaveBeenCalledWith('video-1');
  await act(async () => { screen.unmount(); });
});

const catalogLip: Product = {
  id: 'real-lip', brand: 'Brand', name: 'Lip Product', nameKo: 'Lip Product', category: 'lip',
  makeupZone: 'lip', texture: 'matte', priceKRW: 10000, volume: '', description: '',
  keyIngredients: [], tags: [], imageUrl: '', searchKeyword: '',
  shades: [{ id: 'first', name: 'First', hex: '#112233' }, { id: 'second', name: 'Second', hex: '#334455' }],
};
const listed: StyleLookProduct = { number: 1, brand: 'Brand', name: 'Lip Product', option: 'Second',
  zone: '립', category: 'lip', reviewStatus: 'unverified' };

test('passes the selected video namespace and exact look ID into style chat', async () => {
  let view!: renderer.ReactTestRenderer;
  await act(async () => { view = renderer.create(<StyleLookDetail />); });
  await act(async () => { buttons(view, 'chat.style.openGuide')[0].props.onPress(); });
  expect(mockPush).toHaveBeenCalledWith({ pathname: '/chat', params: { recipeKind: 'video', recipeLookId: 'video-1' } });
  await act(async () => view.unmount());
});

function buttons(screen: renderer.ReactTestRenderer, label: string) {
  return screen.root.findAll((node) => typeof node.props.onPress === 'function').filter((button) =>
    button.findAllByType(Text).some((text) => text.props.children === label));
}

test.each(['원문에 명시 정보 없음', 'No such shade', 'Second'])(
  'name-only product keeps detail/manual selection without automatic AR: %s', async (option) => {
    mockCatalog = [catalogLip]; mockItems = [{ ...listed, option }];
    let screen!: renderer.ReactTestRenderer;
    await act(async () => { screen = renderer.create(<StyleLookDetail />); });
    expect(buttons(screen, 'styleLooks.tryAr')).toHaveLength(0);
    expect(screen.root.findAllByType(Text).some((text) => text.props.children === 'videoAr.none')).toBe(true);
    await act(async () => { buttons(screen, 'styleLooks.openProduct')[0].props.onPress(); });
    expect(mockPush).toHaveBeenCalledWith({ pathname: '/product/[id]', params: { id: 'real-lip' } });
    await act(async () => { buttons(screen, 'videoAr.button')[0].props.onPress(); });
    expect(mockOpen).toHaveBeenCalledTimes(1);
    expect(screen.root.findAllByType(Text).some((text) => text.props.children === 'styleLooks.matched')).toBe(false);
    await act(async () => { screen.unmount(); });
  });

test('verified mapping uses the exact catalog IDs rather than listed names or the first shade', async () => {
  mockCatalog = [catalogLip]; mockItems = [{ ...listed, name: 'Old display name', mappingVerified: true,
    catalogProductId: 'real-lip', catalogShadeId: 'second' }];
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<StyleLookDetail />); });
  await act(async () => { buttons(screen, 'styleLooks.tryAr')[0].props.onPress(); });
  expect(mockPush).toHaveBeenCalledWith({ pathname: '/ar', params: { productId: 'real-lip', shadeId: 'second' } });
  await act(async () => { screen.unmount(); });
});
