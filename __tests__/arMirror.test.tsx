import React from 'react';
import renderer, { act } from 'react-test-renderer';
import ArTryOnScreen from '@/app/(tabs)/ar';
import { DEMO_PRODUCTS } from '@/lib/devCatalog/demo';
import { useMakeupStore } from '@/store/makeupStore';
import { useSettingsStore } from '@/store/settingsStore';

jest.mock('react-native-safe-area-context', () => {
  const actual = jest.requireActual('react-native-safe-area-context') as typeof import('react-native-safe-area-context');
  return { ...actual, useSafeAreaInsets: () => ({ top: 0, right: 0, bottom: 0, left: 0 }) };
});
jest.mock('@expo/vector-icons/Ionicons', () => 'Ionicons');
jest.mock('expo-camera', () => ({ useCameraPermissions: () => [{ granted: true, canAskAgain: true }, jest.fn()] }));
jest.mock('expo-haptics', () => ({
  selectionAsync: jest.fn(() => Promise.resolve()),
  notificationAsync: jest.fn(() => Promise.resolve()),
  NotificationFeedbackType: { Success: 'success' },
}));
jest.mock('expo-router', () => {
  const { useEffect } = require('react') as typeof import('react');
  const navigation = { setOptions: jest.fn() };
  const router = { push: jest.fn(), back: jest.fn(), canGoBack: () => false };
  return {
    useRouter: () => router,
    useLocalSearchParams: () => ({}),
    useNavigation: () => navigation,
    useFocusEffect: (cb: () => void | (() => void)) => {
      useEffect(() => {
        const cleanup = cb();
        return typeof cleanup === 'function' ? cleanup : undefined;
      }, [cb]);
    },
  };
});
jest.mock('expo-linear-gradient', () => ({ LinearGradient: 'LinearGradient' }));
jest.mock('@/components/ar/ArFaceView', () => ({ ArFaceView: 'ArFaceView' }));
jest.mock('@/lib/i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }));
jest.mock('@/hooks/useArRouteSelection', () => ({ useArRouteSelection: () => ({ product: {} }) }));
jest.mock('@/lib/queries', () => ({ useProducts: () => ({ data: require('@/lib/devCatalog/demo').DEMO_PRODUCTS }) }));

it('folds the product panel without clearing makeup, then restores the same selection', async () => {
  useMakeupStore.getState().reset();
  useSettingsStore.setState({ cameraConsent: true });
  const lip = DEMO_PRODUCTS.find((product) => product.makeupZone === 'lip')!;
  const shade = lip.shades[0]!;
  useMakeupStore.getState().applyShade(lip, shade);

  let screen!: renderer.ReactTestRenderer;
  await act(async () => {
    screen = renderer.create(<ArTryOnScreen />);
  });

  const fold = screen.root.findByProps({ accessibilityLabel: 'ar.mirror.enter' });
  await act(async () => {
    fold.props.onPress();
  });

  expect(screen.root.findAll((node) => node.props.accessibilityLabel === 'ar.mirror.enter' && typeof node.props.onPress === 'function')).toHaveLength(0);
  expect(screen.root.findByProps({ accessibilityLabel: 'ar.mirror.exit' })).toBeTruthy();
  expect(useMakeupStore.getState().selections.lip).toEqual({ productId: lip.id, shadeId: shade.id });
  expect(useMakeupStore.getState().makeup.lip?.hex).toBe(shade.hex);

  await act(async () => {
    screen.root.findByProps({ accessibilityLabel: 'ar.mirror.exit' }).props.onPress();
  });

  expect(screen.root.findByProps({ accessibilityLabel: 'ar.mirror.enter' })).toBeTruthy();
  expect(useMakeupStore.getState().selections.lip).toEqual({ productId: lip.id, shadeId: shade.id });
  await act(async () => {
    screen.unmount();
  });
});
