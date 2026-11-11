import AsyncStorage from '@react-native-async-storage/async-storage';
import { Text } from 'react-native';
import { HomeChatButton } from '@/components/chat/HomeChatButton';
import React from 'react';
import renderer, { act, type ReactTestRenderer } from 'react-test-renderer';
import StyleLookDetail from '@/app/style-look/[id]';
import { openYoutubeVideo } from '@/components/celeb/VideoCard';

const mockPush = jest.fn();
const mockProductsById = { p1: { id: 'p1', makeupZone: 'lip', texture: 'matte', shades: [{ id: 's1', name: 'Pink', hex: '#112233' }] } };
const mockLookProducts = [
  { number: 1, brand: 'A', name: 'Lip', option: '원문에 명시 정보 없음', zone: '립' },
  { number: 2, brand: 'B', name: 'Shadow', option: '02', zone: '아이섀도' },
  { number: 3, brand: 'C', name: 'Lip 2', option: '03', zone: '립' },
];

jest.mock('expo-router', () => ({
  Stack: { Screen: ({ options }: { options: { headerRight?: () => unknown } }) => options.headerRight?.() ?? null },
  useLocalSearchParams: () => ({ id: 'video-1' }),
  useRouter: () => ({ push: mockPush, back: jest.fn(), canGoBack: () => false }),
}));
jest.mock('@expo/vector-icons/Ionicons', () => 'Ionicons');
jest.mock('expo-linear-gradient', () => ({ LinearGradient: 'LinearGradient' }));
jest.mock('@/components/celeb/VideoCard', () => ({ openYoutubeVideo: jest.fn(() => Promise.resolve()) }));
jest.mock('@/components/celeb/YoutubePlayer', () => ({ YoutubePlayer: 'YoutubePlayer' }));
jest.mock('@/hooks/useVideoTryOn', () => ({ useVideoTryOn: () => ({ open: jest.fn(), loading: false, error: false, count: 0, selectedIndices: new Set(), productsById: mockProductsById }) }));
jest.mock('@/components/ui/StateViews', () => ({ EmptyState: 'EmptyState', ErrorState: 'ErrorState', LoadingState: 'LoadingState' }));
jest.mock('@/lib/i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }));
jest.mock('@/lib/queries', () => ({
  useProducts: () => ({ data: [] }),
  useStyleLooks: () => ({ isPending: false, isError: false, data: [{
    id: 'video-1', title: 'Example look', tag: '#look', group: '컬러·톤 스타일',
    products: mockLookProducts,
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

test('style detail shows links only for approved products and shade', async () => {
  Object.assign(mockLookProducts[0], { mappingVerified: true, catalogProductId: 'p1', catalogShadeId: 's1' });
  mockPush.mockClear();
  let screen!: renderer.ReactTestRenderer;
  try {
    await act(async () => { screen = renderer.create(<StyleLookDetail />); });
    const text = screen.root.findAllByType(Text).map((node) => node.props.children);
    expect(text.filter((value) => value === 'videoAr.verifiedProduct')).toHaveLength(1);
    expect(text.filter((value) => value === 'styleLooks.tryAr')).toHaveLength(1);
    const buttons = screen.root.findAll((node) => typeof node.type === 'string' && node.props.accessibilityRole === 'button');
    const action = (label: string) => buttons.find((button) => button.findAllByType(Text).some((node) => node.props.children === label))!;
    await act(async () => { action('styleLooks.openProduct').props.onClick(); action('styleLooks.tryAr').props.onClick(); });
    expect(mockPush).toHaveBeenCalledWith({ pathname: '/product/[id]', params: { id: 'p1', shade: 's1' } });
    expect(mockPush).toHaveBeenCalledWith({ pathname: '/ar', params: { productId: 'p1', shadeId: 's1' } });
  } finally {
    delete (mockLookProducts[0] as Record<string, unknown>).mappingVerified;
    delete (mockLookProducts[0] as Record<string, unknown>).catalogProductId;
    delete (mockLookProducts[0] as Record<string, unknown>).catalogShadeId;
    await act(async () => { screen?.unmount(); });
  }
});

test('opens the guide for the exact video', async () => {
  mockPush.mockClear();
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<StyleLookDetail />); });
  const guide = screen.root.findAll((node) => node.props.accessibilityLabel === 'home.chatFab')[0];
  await act(async () => { guide.props.onPress(); });
  expect(mockPush).toHaveBeenCalledWith({ pathname: '/chat', params: { recipeKind: 'video', recipeLookId: 'video-1' } });
  await act(async () => { screen.unmount(); });
});


test('the AI button saves a bounded relative drag, suppresses navigation and can reset', async () => {
  const open = jest.fn();
  let view!: ReactTestRenderer;
  await act(async () => { view = renderer.create(React.createElement(HomeChatButton, { label: 'AI test', hint: 'Open', onPress: open })); });
  const button = () => {
    const item = view.root.findAll((node) => node.props.accessibilityLabel === 'AI test' && typeof node.props.onLongPress === 'function')[0];
    if (!item) throw new Error('AI button gesture handlers were not rendered');
    return item;
  };
  const layout = (width: number, height: number) => {
    const item = view.root.findAll((node) => typeof node.props.onLayout === 'function')[0];
    if (!item) throw new Error('AI button layout handler was not rendered');
    item.props.onLayout({ nativeEvent: { layout: { width, height } } });
  };
  await act(async () => layout(300, 500));
  const start = { nativeEvent: { pageX: 250, pageY: 400 } };
  const end = { nativeEvent: { pageX: -1000, pageY: -1000, touches: [{}] } };
  await act(async () => {
    button().props.onTouchStart(start);
    button().props.onLongPress();
    button().props.onTouchMove(end);
    button().props.onTouchEnd();
    button().props.onPress();
  });
  const storageKey = 'vishue.chat.fab-position.v1';
  expect(open).not.toHaveBeenCalled();
  expect(JSON.parse((await AsyncStorage.getItem(storageKey))!)).toEqual({ x: 0, y: 0 });
  await act(async () => view.unmount());
  await act(async () => { view = renderer.create(React.createElement(HomeChatButton, { label: 'AI test', hint: 'Open', onPress: open })); });
  await act(async () => layout(400, 310));
  expect(button().props.style({ pressed: false })[1]).toMatchObject({ left: 18, top: 18 });
  await act(async () => button().props.onAccessibilityAction({ nativeEvent: { actionName: 'resetPosition' } }));
  expect(JSON.parse((await AsyncStorage.getItem(storageKey))!)).toEqual({ x: 1, y: 1 });
  await act(async () => { button().props.onTouchStart(start); button().props.onTouchEnd(); button().props.onPress(); });
  expect(open).toHaveBeenCalledTimes(1);
  await act(async () => view.unmount());
});
