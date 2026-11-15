import renderer, { act } from 'react-test-renderer';
import { Animated, Modal } from 'react-native';
import { NearbyDirectionDial } from '@/components/ar/NearbyDirectionDial';
import { arcSnapEasing } from '@/components/ar/arcMotion';
import type { NearbyDirection } from '@/lib/nearbyColors';

jest.mock('@expo/vector-icons/Ionicons', () => 'Ionicons');
jest.mock('@/lib/i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }));
jest.mock('react-native-safe-area-context', () => ({ useSafeAreaInsets: () => ({ top: 0, right: 0, bottom: 0, left: 0 }) }));

const counts = { similar: 4, lighter: 2, darker: 0, muted: 1, vivid: 3 };
const event = (y: number, x = 200) => ({ nativeEvent: { pageX: x, pageY: y } });
let screen: renderer.ReactTestRenderer;
let select: jest.Mock;

beforeEach(async () => {
  jest.useFakeTimers();
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
  select = jest.fn();
  await act(async () => { screen = renderer.create(<NearbyDirectionDial direction="similar" counts={counts} onDirection={select} />); });
  screen.root.findByProps({ testID: 'ar-direction-anchor' }).instance.measureInWindow.mockImplementation(
    (callback: (x: number, y: number, width: number, height: number) => void) => callback(330, 424, 44, 44),
  );
});

afterEach(async () => {
  await act(async () => { screen.unmount(); });
  jest.restoreAllMocks();
  jest.useRealTimers();
});

const open = async () => { await act(async () => { screen.root.findByProps({ accessibilityLabel: 'ar.arc.direction' }).props.onPress(); }); };
const settle = async () => { await act(async () => { jest.advanceTimersByTime(300); }); };
const choose = async (direction: NearbyDirection) => {
  await act(async () => { screen.root.findByProps({ accessibilityLabel: `ar.explore.${direction} · ${counts[direction]}` }).props.onPress(); });
};

it('opens on demand, commits a tapped direction once after snapping, and preserves empty directions', async () => {
  expect(screen.root.findAllByType(Modal)).toHaveLength(0);
  await open();
  await choose('darker');
  expect(select).not.toHaveBeenCalled();
  expect(Animated.timing).toHaveBeenLastCalledWith(expect.anything(), expect.objectContaining({ duration: 240, easing: arcSnapEasing }));
  await settle();
  expect(select).toHaveBeenCalledTimes(1);
  expect(select).toHaveBeenCalledWith('darker');
  expect(screen.root.findAllByType(Modal)).toHaveLength(0);
});

it('previews a vertical drag without changing candidates, then clamps and snaps on release', async () => {
  await open();
  const scale = () => screen.root.findByProps({ testID: 'ar-direction-scale' });
  await act(async () => {
    scale().props.onStartShouldSetResponderCapture(event(360));
    expect(scale().props.onMoveShouldSetResponderCapture(event(365, 240))).toBe(false);
    expect(scale().props.onMoveShouldSetResponderCapture(event(400))).toBe(true);
    scale().props.onResponderGrant(event(400));
    scale().props.onResponderMove(event(999));
  });
  expect(select).not.toHaveBeenCalled();
  expect(screen.root.findByProps({ accessibilityLabel: 'ar.explore.vivid · 3' }).props.accessibilityState.selected).toBe(true);
  await act(async () => { scale().props.onResponderRelease(event(999)); });
  await settle();
  expect(select).toHaveBeenCalledWith('vivid');
});

it('cancels a pending snap on backdrop/back dismissal without changing candidates', async () => {
  await open();
  await choose('muted');
  await act(async () => { screen.root.findByType(Modal).props.onRequestClose(); });
  await settle();
  expect(select).not.toHaveBeenCalled();
  expect(screen.root.findAllByType(Modal)).toHaveLength(0);
});

it('drops a pending choice when the mode unmounts the dial', async () => {
  await open();
  await choose('lighter');
  await act(async () => { screen.unmount(); });
  await settle();
  expect(select).not.toHaveBeenCalled();
});

it('cancels a pending choice on external direction changes and does not reopen stale geometry', async () => {
  await open();
  await choose('muted');
  await act(async () => { screen.update(<NearbyDirectionDial direction="lighter" counts={counts} onDirection={select} />); });
  await settle();
  expect(select).not.toHaveBeenCalled();
  expect(screen.root.findAllByType(Modal)).toHaveLength(0);
  await act(async () => { screen.update(<NearbyDirectionDial direction="similar" counts={counts} onDirection={select} />); });
  expect(screen.root.findAllByType(Modal)).toHaveLength(0);
});
