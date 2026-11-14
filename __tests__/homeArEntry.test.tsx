import React from 'react';
import renderer, { act } from 'react-test-renderer';
import TabLayout from '@/app/(tabs)/_layout';
import { MAKEUP_ZONES, useMakeupStore } from '@/store/makeupStore';
import type { CelebLook } from '@/types';

jest.mock('@expo/vector-icons/Ionicons', () => 'Ionicons');
jest.mock('@/components/chat/HomeChatButton', () => ({ HomeChatButton: 'HomeChatButton' }));
jest.mock('@/lib/i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }));
jest.mock('expo-router', () => {
  const React = require('react') as typeof import('react');
  const Tabs = ({ children }: { children: React.ReactNode }) => React.createElement('Tabs', null, children);
  Tabs.Screen = (props: object) => React.createElement('TabScreen', props);
  return { Tabs, useRouter: () => ({ push: jest.fn() }) };
});

const look = {
  id: 'e1gSkUdG6Bo', title: 'Video look', items: [],
  makeup: {
    lip: { hex: '#a24a59', intensity: 0.6, texture: 'glossy' },
    blush: { hex: '#ed9fab', intensity: 0.4, texture: 'sheer' },
  },
} as unknown as CelebLook;

afterEach(() => useMakeupStore.getState().reset());

it('starts a clean AR session when the home tab opens the AR tab after a video look', async () => {
  useMakeupStore.getState().applyLook(look, []);
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<TabLayout />); });
  const arTab = screen.root.findAllByType('TabScreen' as never).find((node) => node.props.name === 'ar')!;
  const navigation = {
    getState: () => ({ index: 0, routes: [{ name: 'index' }, { name: 'ar' }] }),
    navigate: jest.fn(),
  };
  const event = { preventDefault: jest.fn() };
  await act(async () => { arTab.props.listeners({ navigation }).tabPress(event); });

  expect(event.preventDefault).toHaveBeenCalled();
  expect(navigation.navigate).toHaveBeenCalledWith('ar', {
    video: undefined, productId: undefined, shadeId: undefined, compare: undefined,
  }, { merge: false });
  const state = useMakeupStore.getState();
  expect(state.activeLook).toBeNull();
  expect(state.selections).toEqual({});
  for (const zone of MAKEUP_ZONES) expect(state.makeup[zone]).toBeNull();
  await act(async () => { screen.unmount(); });
});

it('does not clear the current look when the AR tab is pressed from another tab', async () => {
  useMakeupStore.getState().applyLook(look, []);
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<TabLayout />); });
  const arTab = screen.root.findAllByType('TabScreen' as never).find((node) => node.props.name === 'ar')!;
  const navigation = {
    getState: () => ({ index: 0, routes: [{ name: 'celeb' }, { name: 'ar' }] }),
    navigate: jest.fn(),
  };
  const event = { preventDefault: jest.fn() };
  await act(async () => { arTab.props.listeners({ navigation }).tabPress(event); });
  expect(event.preventDefault).not.toHaveBeenCalled();
  expect(navigation.navigate).not.toHaveBeenCalled();
  expect(useMakeupStore.getState().activeLook?.id).toBe(look.id);
  expect(useMakeupStore.getState().makeup.lip).not.toBeNull();
  await act(async () => { screen.unmount(); });
});
