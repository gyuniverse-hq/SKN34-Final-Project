import renderer, { act } from 'react-test-renderer';
import { Animated, Platform, Pressable, StyleSheet } from 'react-native';
import { ArZoneWheel, zoneWheelRadius } from '@/components/ar/ArZoneWheel';
import { OpenArcPalette } from '@/components/ar/OpenArcPalette';
import { arcSnapEasing } from '@/components/ar/arcMotion';
import type { ColorSwatch } from '@/lib/nearbyColors';
import type { Product } from '@/types';

jest.mock('@expo/vector-icons/Ionicons', () => 'Ionicons');
let mockWindowWidth = 390;
jest.mock('react-native/Libraries/Utilities/useWindowDimensions', () => ({
  __esModule: true, default: () => ({ width: mockWindowWidth, height: 844, scale: 1, fontScale: 1 }),
}));
const product: Product = {
  id: 'lip', brand: 'Brand', name: 'Lip', nameKo: '립', category: 'lip', makeupZone: 'lip', texture: 'matte',
  priceKRW: 12000, volume: '', description: '', keyIngredients: [], tags: [], imageUrl: '', searchKeyword: '', shades: [],
};
const items: ColorSwatch[] = Array.from({ length: 200 }, (_, i) => ({ product, shade: { id: String(i), name: 'Shade ' + i, hex: '#B05262' } }));

describe('rotating open arc', () => {
  beforeEach(() => {
    jest.useFakeTimers();
    // Model the native animation completion/cancellation contract, not its rendering engine.
    jest.spyOn(Animated, 'timing').mockImplementation((value, config) => {
      let timer: ReturnType<typeof setTimeout> | undefined;
      let done: ((result: { finished: boolean }) => void) | undefined;
      return {
        start(callback) {
          done = callback;
          timer = setTimeout(() => {
            (value as Animated.Value).setValue(config.toValue as number);
            done?.({ finished: true });
          }, config.duration);
        },
        stop() { clearTimeout(timer); done?.({ finished: false }); },
        reset() { clearTimeout(timer); },
      };
    });
  });
  afterEach(() => { jest.restoreAllMocks(); jest.useRealTimers(); });

  const event = (x: number, y = 0, timestamp = 0) => ({ nativeEvent: { pageX: x, pageY: y, timestamp } });
  const palette = (screen: renderer.ReactTestRenderer) => screen.root.findByProps({ testID: 'ar-arc-palette' });
  const finish = async () => { await act(async () => { jest.advanceTimersByTime(800); }); };

  it('renders a bounded window, rotates a tapped shade into place, and only then applies it', async () => {
    const select = jest.fn();
    let screen!: renderer.ReactTestRenderer;
    await act(async () => { screen = renderer.create(<OpenArcPalette items={items} selected={items[0]} label="palette" hint="swipe" onSelect={select} />); });
    expect(select).not.toHaveBeenCalled();
    expect(screen.root.findAllByType(Pressable).length).toBeLessThan(24);
    await act(async () => { screen.root.findByProps({ accessibilityLabel: 'Brand Lip Shade 2' }).props.onPress(); });
    expect(select).not.toHaveBeenCalled();
    expect(Animated.timing).toHaveBeenLastCalledWith(expect.anything(), expect.objectContaining({ easing: arcSnapEasing, useNativeDriver: true }));
    await finish();
    expect(select).toHaveBeenLastCalledWith(items[2]);
    expect(select).toHaveBeenCalledTimes(1);
    await act(async () => { screen.unmount(); });
  });

  it('clamps short candidate lists and does not change the face during the drag', async () => {
    const select = jest.fn();
    let screen!: renderer.ReactTestRenderer;
    await act(async () => { screen = renderer.create(<OpenArcPalette items={items.slice(0, 3)} selected={items[0]} label="palette" hint="swipe" onSelect={select} />); });
    await act(async () => {
      palette(screen).props.onStartShouldSetResponderCapture(event(200));
      expect(palette(screen).props.onMoveShouldSetResponderCapture(event(180, 2))).toBe(true);
      expect(palette(screen).props.onMoveShouldSetResponderCapture(event(200, 30))).toBe(false);
      palette(screen).props.onResponderGrant(event(-9999, 0, 16));
    });
    expect(select).not.toHaveBeenCalled();
    await act(async () => { palette(screen).props.onResponderRelease(event(-9999, 0, 120)); });
    await finish();
    expect(select).toHaveBeenLastCalledWith(items[2]);
    select.mockClear();
    await act(async () => {
      palette(screen).props.onStartShouldSetResponderCapture(event(200));
      palette(screen).props.onResponderGrant(event(9999, 0, 16));
      palette(screen).props.onResponderRelease(event(9999, 0, 120));
    });
    await finish();
    expect(select).not.toHaveBeenCalled(); // Already previewing the first shade.
    await act(async () => { screen.unmount(); });
  });

  it('loops backward across the catalog boundary without duplicating the full catalog', async () => {
    const select = jest.fn();
    let screen!: renderer.ReactTestRenderer;
    await act(async () => { screen = renderer.create(<OpenArcPalette items={items} selected={items[0]} label="palette" hint="swipe" onSelect={select} />); });
    await act(async () => {
      palette(screen).props.onStartShouldSetResponderCapture(event(200));
      palette(screen).props.onResponderGrant(event(265, 0, 300));
      palette(screen).props.onResponderRelease(event(265, 0, 500));
    });
    await finish();
    expect(select).toHaveBeenLastCalledWith(items[199]);
    expect(screen.root.findAllByType(Pressable).length).toBeLessThan(24);
    await act(async () => { screen.unmount(); });
  });

  it('cancels pending shade application when candidates change or the palette unmounts', async () => {
    const select = jest.fn();
    let screen!: renderer.ReactTestRenderer;
    const render = (list: readonly ColorSwatch[]) => <OpenArcPalette items={list} selected={items[0]} label="palette" hint="swipe" onSelect={select} />;
    await act(async () => { screen = renderer.create(render(items)); });
    await act(async () => { screen.root.findByProps({ accessibilityLabel: 'Brand Lip Shade 2' }).props.onPress(); });
    await act(async () => { screen.update(render([])); });
    await finish();
    expect(select).not.toHaveBeenCalled();
    expect(screen.root.findAllByType(Pressable)).toHaveLength(0);
    await act(async () => { screen.update(render(items)); });
    await act(async () => { screen.root.findByProps({ accessibilityLabel: 'Brand Lip Shade 1' }).props.onPress(); screen.unmount(); });
    await finish();
    expect(select).not.toHaveBeenCalled();
  });

  it('lets a new choice interrupt a spin and cancels a terminated gesture', async () => {
    const select = jest.fn();
    let screen!: renderer.ReactTestRenderer;
    await act(async () => { screen = renderer.create(<OpenArcPalette items={items} selected={items[0]} label="palette" hint="swipe" onSelect={select} />); });
    await act(async () => { screen.root.findByProps({ accessibilityLabel: 'Brand Lip Shade 2' }).props.onPress(); });
    await act(async () => { screen.root.findByProps({ accessibilityLabel: 'Brand Lip Shade 1' }).props.onPress(); });
    await finish();
    expect(select).toHaveBeenCalledTimes(1);
    expect(select).toHaveBeenLastCalledWith(items[1]);
    select.mockClear();
    await act(async () => {
      palette(screen).props.onStartShouldSetResponderCapture(event(200));
      palette(screen).props.onResponderGrant(event(110, 0, 100));
      palette(screen).props.onResponderTerminate();
    });
    await finish();
    expect(select).not.toHaveBeenCalled();
    await act(async () => { screen.unmount(); });
  });

  it('settles web wheel input and supports accessible one-slot adjustment without selecting on mount', async () => {
    const platform = jest.replaceProperty(Platform, 'OS', 'web');
    const select = jest.fn();
    let screen!: renderer.ReactTestRenderer;
    try {
      await act(async () => { screen = renderer.create(<OpenArcPalette items={items} selected={items[0]} label="palette" hint="swipe" onSelect={select} />); });
      await finish();
      expect(select).not.toHaveBeenCalled();
      await act(async () => { palette(screen).props.onWheel({ nativeEvent: { deltaX: 110, deltaY: 0 } }); });
      expect(select).not.toHaveBeenCalled();
      await finish();
      expect(select).toHaveBeenLastCalledWith(items[2]);
      await act(async () => { palette(screen).props.onAccessibilityAction({ nativeEvent: { actionName: 'increment' } }); });
      await finish();
      expect(select).toHaveBeenLastCalledWith(items[3]);
    } finally {
      await act(async () => { screen.unmount(); });
      platform.restore();
    }
  });
});

it('uses exactly 20% acceleration and 80% deceleration, with continuous speed and no bounce', () => {
  expect(arcSnapEasing(0)).toBe(0);
  expect(arcSnapEasing(1)).toBe(1);
  const speed = (t: number) => (arcSnapEasing(t + 0.0001) - arcSnapEasing(t - 0.0001)) / 0.0002;
  expect(speed(0.1)).toBeLessThan(speed(0.19));
  expect(speed(0.19)).toBeLessThan(speed(0.2));
  expect(speed(0.2)).toBeGreaterThan(speed(0.3));
  expect(speed(0.3)).toBeGreaterThan(speed(0.8));
  expect(speed(0.2 - 0.0001)).toBeCloseTo(speed(0.2 + 0.0001), 2);
  const points = Array.from({ length: 101 }, (_, i) => arcSnapEasing(i / 100));
  expect(points).toEqual([...points].sort((a, b) => a - b));
  expect(points.every((value) => value >= 0 && value <= 1)).toBe(true);
});

describe('category wheel', () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());
  const event = (x: number, y: number) => ({ nativeEvent: { pageX: x, pageY: y } });
  const props = { zones: ['lip', 'blush', 'eyeshadow'] as const, selected: 'lip' as const, labels: { lip: 'Lip', blush: 'Blush', eyeshadow: 'Eyes' }, hint: 'hold', openLabel: 'areas', closeLabel: 'close' };
  it.each([320, 390])('keeps every label box inside its own wedge at %ipx width', async (width) => {
    mockWindowWidth = width;
    const zones = ['lip', 'blush', 'eyeshadow', 'eyeliner', 'highlighter', 'contour', 'brow', 'foundation'] as const;
    const labels = { lip: '립', blush: '블러셔', eyeshadow: '아이섀도우', eyeliner: '아이라이너', highlighter: '하이라이터', contour: '쉐딩', brow: '아이브로우', foundation: '파운데이션' };
    let screen!: renderer.ReactTestRenderer;
    try {
      await act(async () => { screen = renderer.create(<ArZoneWheel {...props} zones={zones} labels={labels} onSelect={jest.fn()} />); });
      await act(async () => { screen.root.findByProps({ accessibilityLabel: 'areas' }).props.onAccessibilityAction(); });
      const radius = zoneWheelRadius(width);
      zones.forEach((zone, index) => {
        const label = screen.root.findByProps({ accessibilityLabel: labels[zone] });
        const box = StyleSheet.flatten(label.props.style);
        expect(box.width).toBeGreaterThan(16);
        for (const x of [box.left, box.left + box.width]) {
          for (const y of [box.top, box.top + box.height]) {
            const dx = x - width / 2;
            const dy = y - radius - 1;
            const angle = Math.atan2(dy, dx) + Math.PI * 2;
            expect(angle).toBeGreaterThanOrEqual(Math.PI + index * Math.PI / zones.length);
            expect(angle).toBeLessThanOrEqual(Math.PI + (index + 1) * Math.PI / zones.length);
            expect(Math.hypot(dx, dy)).toBeLessThan(radius);
            expect(Math.hypot(dx, dy)).toBeGreaterThan(radius * 0.36);
          }
        }
      });
    } finally {
      await act(async () => { screen.unmount(); });
      mockWindowWidth = 390;
    }
  });
  it('supports tap-open selection without a long press', async () => {
    const select = jest.fn();
    let screen!: renderer.ReactTestRenderer;
    await act(async () => { screen = renderer.create(<ArZoneWheel {...props} onSelect={select} />); });
    const hub = () => screen.root.findByProps({ accessibilityLabel: 'areas' });
    await act(async () => { hub().props.onResponderGrant(event(200, 500)); hub().props.onResponderRelease(event(200, 500)); });
    expect(hub().props.accessibilityState.expanded).toBe(true);
    await act(async () => { screen.root.findByProps({ accessibilityLabel: 'Blush' }).props.onPress(); });
    expect(select).toHaveBeenCalledWith('blush');
    expect(hub().props.accessibilityState.expanded).toBe(false);
    await act(async () => { screen.unmount(); });
    await act(async () => { jest.advanceTimersByTime(400); });
    expect(select).toHaveBeenCalledTimes(1);
  });
  it('selects the hovered sector on hold-drag-release and cancels interrupted gestures', async () => {
    const select = jest.fn();
    let screen!: renderer.ReactTestRenderer;
    await act(async () => { screen = renderer.create(<ArZoneWheel {...props} onSelect={select} />); });
    const hub = () => screen.root.findByProps({ accessibilityLabel: 'areas' });
    await act(async () => { hub().props.onResponderGrant(event(200, 500)); jest.advanceTimersByTime(350); });
    await act(async () => { hub().props.onResponderMove(event(200, 307)); hub().props.onResponderRelease(event(200, 307)); });
    expect(select).toHaveBeenCalledWith('blush');
    select.mockClear();
    await act(async () => { hub().props.onResponderGrant(event(200, 500)); hub().props.onResponderTerminate(); jest.advanceTimersByTime(400); });
    expect(hub().props.accessibilityState.expanded).toBe(false);
    expect(select).not.toHaveBeenCalled();
    await act(async () => { screen.unmount(); });
  });
  it('selects the whole annular sector and leaves the center opening as a cancel area', async () => {
    const select = jest.fn();
    const expanded = jest.fn();
    let screen!: renderer.ReactTestRenderer;
    await act(async () => { screen = renderer.create(<ArZoneWheel {...props} onSelect={select} onOpenChange={expanded} />); });
    const hub = () => screen.root.findByProps({ accessibilityLabel: 'areas' });
    await act(async () => { hub().props.onResponderGrant(event(200, 500)); hub().props.onResponderRelease(event(200, 500)); });
    expect(expanded).toHaveBeenLastCalledWith(true);
    const fan = screen.root.findByProps({ testID: 'ar-zone-fan' });
    expect(fan.props.onStartShouldSetResponderCapture(event(200, 480))).toBe(false);
    expect(fan.props.onStartShouldSetResponderCapture(event(200, 250))).toBe(false);
    expect(fan.props.onStartShouldSetResponderCapture(event(200, 400))).toBe(true);
    await act(async () => { fan.props.onResponderRelease(event(200, 400)); });
    expect(select).toHaveBeenCalledWith('blush');
    await act(async () => { screen.unmount(); });
    expect(expanded).toHaveBeenLastCalledWith(false);
  });
});
