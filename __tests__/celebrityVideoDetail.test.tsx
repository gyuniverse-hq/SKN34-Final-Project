import React from 'react';
import { Text } from 'react-native';
import renderer, { act } from 'react-test-renderer';
import CelebrityVideoDetail from '@/app/celebrity-video/[id]';
import { openYoutubeVideo } from '@/components/celeb/VideoCard';

jest.mock('expo-router', () => ({ Stack: { Screen: () => null }, useLocalSearchParams: () => ({ id: 'video-1' }) }));
jest.mock('@expo/vector-icons/Ionicons', () => 'Ionicons');
jest.mock('expo-image', () => ({ Image: 'MockImage' }));
jest.mock('expo-linear-gradient', () => ({ LinearGradient: 'LinearGradient' }));
jest.mock('@/components/celeb/VideoCard', () => ({ openYoutubeVideo: jest.fn(() => Promise.resolve()) }));
jest.mock('@/components/celeb/YoutubePlayer', () => ({ YoutubePlayer: 'YoutubePlayer' }));
jest.mock('@/components/ui/StateViews', () => ({ EmptyState: 'EmptyState', ErrorState: 'ErrorState', LoadingState: 'LoadingState' }));
jest.mock('@/lib/i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }));
jest.mock('@/lib/queries', () => ({
  useCelebrityVideos: () => ({ isPending: false, isError: false, data: [{
    id: 'video-1', celebrityId: 'karina', title: 'Video title', channelName: 'Channel', number: 1,
    startSeconds: 1582, linkStatus: 'needs_review', products: [
      { number: 1, brand: 'A', name: 'Lip', option: '원본에 별도 옵션 없음', zone: '입술', reviewStatus: '브랜드 확인 필요', sourceType: '제품제공' },
      { number: 2, brand: 'B', name: 'Eye', option: '02', zone: '눈', reviewStatus: '원본 기준 정리', sourceType: '미기재' },
    ],
  }] }),
}));

test('shows video and review details and opens the specified starting point', async () => {
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<CelebrityVideoDetail />); });
  let text = screen.root.findAllByType(Text).map((node) => node.props.children);
  expect(text).toContain('styleLooks.zone.lip');
  expect(text).toContain('styleLooks.zone.eye');
  expect(text).not.toContain('celebVideo.brandReview');
  const lip = screen.root.findByProps({ accessibilityLabel: 'styleLooks.zone.lip, looks.itemCount' });
  expect(lip.props.accessibilityState.expanded).toBe(false);
  await act(async () => { lip.props.onPress(); });
  text = screen.root.findAllByType(Text).map((node) => node.props.children);
  expect(text).toContain('celebVideo.brandReview');
  expect(text).toContain('celebVideo.source.provided');
  expect(lip.props.accessibilityState.expanded).toBe(true);
  await act(async () => { lip.props.onPress(); });
  expect(screen.root.findAllByType(Text).map((node) => node.props.children)).not.toContain('celebVideo.brandReview');
  expect(text).toContain('celebVideo.linkUnverified');
  expect(screen.root.findByProps({ videoId: 'video-1', startSeconds: 1582 })).toBeTruthy();
  await act(async () => { screen.root.findByProps({ accessibilityRole: 'link' }).props.onPress(); });
  expect(openYoutubeVideo).toHaveBeenCalledWith('video-1', 1582);
  await act(async () => { screen.unmount(); });
});
