import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { YoutubePlayer } from '@/components/celeb/YoutubePlayer';

jest.mock('expo-constants', () => ({
  __esModule: true,
  default: { executionEnvironment: 'storeClient', expoConfig: {} },
  ExecutionEnvironment: { StoreClient: 'storeClient' },
}));
jest.mock('expo-router', () => ({
  useFocusEffect: (callback: () => () => void) => {
    const { useEffect } = require('react') as typeof import('react');
    useEffect(callback, [callback]);
  },
}));
jest.mock('react-native-webview', () => ({ WebView: 'MockWebView' }));

test('loads the official player with the start time and Expo Go identity', async () => {
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<YoutubePlayer videoId="1qj6SactPVM" startSeconds={1582} title="Video" />); });
  const player = screen.root.findByProps({ accessibilityLabel: 'Video' });
  expect(player.props.source).toEqual({
    uri: 'https://www.youtube.com/embed/1qj6SactPVM?playsinline=1&start=1582',
    headers: { Referer: 'https://host.exp.exponent' },
  });
  expect(player.props.mediaPlaybackRequiresUserAction).toBe(true);
  await act(async () => { screen.unmount(); });
});
