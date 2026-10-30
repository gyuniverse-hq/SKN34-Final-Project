import React from 'react';
import { Text } from 'react-native';
import renderer, { act } from 'react-test-renderer';
import StyleLookDetail from '@/app/style-look/[id]';
import { openYoutubeVideo } from '@/components/celeb/VideoCard';

jest.mock('expo-router', () => ({
  Stack: { Screen: () => null },
  useLocalSearchParams: () => ({ id: 'video-1' }),
}));
jest.mock('@expo/vector-icons/Ionicons', () => 'Ionicons');
jest.mock('expo-linear-gradient', () => ({ LinearGradient: 'LinearGradient' }));
jest.mock('@/components/celeb/VideoCard', () => ({ openYoutubeVideo: jest.fn(() => Promise.resolve()) }));
jest.mock('@/components/celeb/YoutubePlayer', () => ({ YoutubePlayer: 'YoutubePlayer' }));
jest.mock('@/hooks/useVideoTryOn', () => ({ useVideoTryOn: () => ({ open: jest.fn(), loading: false, error: false, count: 0, selectedIndices: new Set() }) }));
jest.mock('@/components/ui/StateViews', () => ({ EmptyState: 'EmptyState', ErrorState: 'ErrorState', LoadingState: 'LoadingState' }));
jest.mock('@/lib/i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }));
jest.mock('@/lib/queries', () => ({
  useStyleLooks: () => ({ isPending: false, isError: false, data: [{
    id: 'video-1', title: 'Example look', tag: '#look', group: '컬러·톤 스타일',
    products: [
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
