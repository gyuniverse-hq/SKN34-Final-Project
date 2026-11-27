import React from 'react';
import { AccessibilityInfo, FlatList, StyleSheet, type ViewStyle } from 'react-native';
import renderer, { act } from 'react-test-renderer';
import { ArConversationShades } from '@/components/ar/ArConversationPalette';
import { ArcFeatherView } from '@/components/ar/ArcFeatherView';
import type { Product } from '@/types';

jest.mock('@/lib/i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }));

const product = {
  id: 'lipstick',
  shades: ['#D34F80', '#BD4277', '#B73963', '#C95065', '#C47171', '#9F2A51'].map((hex, i) => ({
    id: String(i), name: 'Shade ' + (i + 1), hex,
  })),
} as Product;

afterEach(() => jest.restoreAllMocks());

it.each([
  { count: 2, index: 1, reduceMotion: false },
  { count: 6, index: 5, reduceMotion: false },
  { count: 6, index: 5, reduceMotion: true },
])('moves to shade $index with $count chips and reduced motion $reduceMotion', async ({ count, index, reduceMotion }) => {
  jest.spyOn(AccessibilityInfo, 'isReduceMotionEnabled').mockResolvedValue(reduceMotion);
  const scroll = jest.spyOn(FlatList.prototype, 'scrollToOffset').mockImplementation(() => {});
  const item = { ...product, shades: product.shades.slice(0, count) };
  const items = item.shades.map(shade => ({ product: item, shade }));
  const onSelect = jest.fn();
  let screen!: renderer.ReactTestRenderer;
  await act(async () => {
    screen = renderer.create(<ArConversationShades items={items} selected={items[0]} onSelect={onSelect} />);
  });
  const strip = screen.root.findByProps({ testID: 'ar-conversation-shade-strip' });
  const track = strip.findByProps({ testID: 'ar-conversation-shade-track' });
  const list = strip.findByType(FlatList);
  const viewport = StyleSheet.flatten<ViewStyle>(strip.props.style);
  expect(viewport?.height).toBe(48);
  expect(strip.findByType(ArcFeatherView).props).toMatchObject({ feather: 20, fadeBottom: false });
  expect(list.props.showsHorizontalScrollIndicator).toBe(false);
  expect(list.props.persistentScrollbar).toBe(false);
  expect(scroll).toHaveBeenCalledWith({ offset: 0, animated: false });

  await act(async () => {
    screen.update(<ArConversationShades items={items} selected={items[index]} onSelect={onSelect} />);
  });
  expect(scroll).toHaveBeenCalledWith({ offset: index * 54, animated: !reduceMotion });
  expect(strip.findByProps({ testID: 'ar-conversation-shade-track' })).toBe(track);
  expect(StyleSheet.flatten<ViewStyle>(strip.props.style)).toEqual(viewport);
  const contentWidth = StyleSheet.flatten<ViewStyle>(track.props.style)?.width;
  expect(Number(contentWidth) - Number(viewport?.width)).toBe((count - 1) * 54);
  expect(screen.root.findByProps({ accessibilityRole: 'radio', accessibilityLabel: item.shades[index].name })
    .props.accessibilityState.checked).toBe(true);
  await act(async () => screen.unmount());
});

it('selects a nearby candidate from a swipe and ignores programmatic scrolling', async () => {
  const items = product.shades.slice(0, 2).map(shade => ({ product, shade }));
  const onSelect = jest.fn();
  let screen!: renderer.ReactTestRenderer;
  await act(async () => {
    screen = renderer.create(<ArConversationShades items={items} selected={items[0]} onSelect={onSelect} selectOnSwipe />);
  });
  const list = screen.root.findByType(FlatList);
  const end = { nativeEvent: { contentOffset: { x: 54, y: 0 } } };
  await act(async () => { list.props.onMomentumScrollEnd(end); });
  expect(onSelect).not.toHaveBeenCalled();
  await act(async () => {
    list.props.onScrollBeginDrag();
    list.props.onScrollEndDrag({ ...end, nativeEvent: { ...end.nativeEvent, velocity: { x: 1, y: 0 } } });
    list.props.onMomentumScrollEnd(end);
  });
  expect(onSelect).toHaveBeenCalledTimes(1);
  expect(onSelect).toHaveBeenCalledWith(items[1]);
  await act(async () => screen.unmount());
});
