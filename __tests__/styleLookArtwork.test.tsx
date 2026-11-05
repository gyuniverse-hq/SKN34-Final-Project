import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { StyleLookArtwork } from '@/components/celeb/StyleLookCard';

jest.mock('@expo/vector-icons/Ionicons', () => 'Ionicons');
jest.mock('expo-image', () => ({ Image: 'MockImage' }));
jest.mock('expo-linear-gradient', () => ({ LinearGradient: 'LinearGradient' }));

test('shows the video thumbnail and falls back when loading fails', async () => {
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<StyleLookArtwork group="컬러·톤 스타일" videoId="1qj6SactPVM" />); });
  const images = () => screen.root.findAll((node) => node.props.source?.uri === 'https://i.ytimg.com/vi/1qj6SactPVM/hqdefault.jpg');
  const picture = images()[0];
  await act(async () => { picture.props.onError(); });
  expect(images()).toHaveLength(0);
  await act(async () => { screen.unmount(); });
});
