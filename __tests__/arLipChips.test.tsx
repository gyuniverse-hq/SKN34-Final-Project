import React from 'react';
import renderer, { act } from 'react-test-renderer';
import ArTryOnScreen from '@/app/(tabs)/ar';
import { Chip } from '@/components/ui/Chip';
import { useMakeupStore } from '@/store/makeupStore';

jest.mock('react-native-safe-area-context', () => {
  const actual = jest.requireActual('react-native-safe-area-context') as typeof import('react-native-safe-area-context');
  return { ...actual, useSafeAreaInsets: () => ({ top: 0, right: 0, bottom: 0, left: 0 }) };
});
jest.mock('@expo/vector-icons/Ionicons', () => 'Ionicons');
jest.mock('expo-camera', () => ({ useCameraPermissions: () => [{ granted: false, canAskAgain: true }, jest.fn()] }));
jest.mock('expo-haptics', () => ({
  notificationAsync: jest.fn(() => Promise.resolve()),
  selectionAsync: jest.fn(() => Promise.resolve()),
  NotificationFeedbackType: { Success: 'success' },
}));
jest.mock('expo-router', () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), canGoBack: () => false }),
  useLocalSearchParams: () => ({}),
  useNavigation: () => ({ setOptions: jest.fn() }),
  useFocusEffect: jest.fn(),
}));
jest.mock('expo-linear-gradient', () => ({ LinearGradient: 'LinearGradient' }));
jest.mock('@/components/ar/ArFaceView', () => ({ ArFaceView: 'ArFaceView' }));
jest.mock('@/lib/i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }));
jest.mock('@/hooks/useArRouteSelection', () => ({ useArRouteSelection: () => ({ product: {} }) }));
jest.mock('@/lib/queries', () => {
  const base = {
    brand: 'B', category: 'lip', makeupZone: 'lip', priceKRW: 0, volume: '', description: '',
    keyIngredients: [], tags: [], imageUrl: '', searchKeyword: '',
  };
  const lip = (id: string, name: string, texture: string, hex: string) =>
    ({ ...base, id, name, nameKo: name, texture, shades: [{ id: 's', name: id, hex }] });
  const products = [
    lip('matte', '매트 립스틱', 'matte', '#B3202E'),
    lip('velvet', '벨벳 틴트', 'velvet', '#A02030'),
    lip('satin', '새틴 립스틱', 'satin', '#C04550'),
    lip('cream', '크림 틴트', 'cream', '#D75C6F'),
    lip('sheer', '시어 틴트', 'sheer', '#E4614F'),
    lip('glossy', '글로시 틴트', 'glossy', '#D9707A'),
    lip('shimmer', '쉬머 립', 'shimmer', '#C8604F'),
    lip('oil', '롬앤 쥬시 플래시 립 오일', 'glossy', '#C5E8F1'),
    lip('balm', '이니스프리 유채꿀 립밤', 'satin', '#F1C7CF'),
    lip('essence', '토리든 솔리드인 세라마이드 립 에센스', 'glossy', '#ECDDAE'),
  ];
  return { useProducts: () => ({ data: products }), useTryOnProducts: () => ({ data: products }) };
});

const chipLabels = (screen: renderer.ReactTestRenderer) => screen.root.findAllByType(Chip).map((c) => c.props.label as string);
const filterChips = (screen: renderer.ReactTestRenderer) =>
  chipLabels(screen).filter((l) => l.startsWith('ar.texture.') || l.startsWith('ar.family.') || l.startsWith('ar.care.') ||
    l === 'ar.filter.all' || l === 'ar.chip.lipCare');
const swatch = (screen: renderer.ReactTestRenderer, id: string) =>
  screen.root.findAll(
    (n) => typeof n.props.accessibilityLabel === 'string' && n.props.accessibilityLabel.endsWith(` ${id}`) && typeof n.props.onPress === 'function'
  )[0];

describe('AR lip tab chips in the tools sheet', () => {
  beforeEach(() => useMakeupStore.getState().reset());

  it('shows finish and care chips alongside the colour-family filters', async () => {
    let screen!: renderer.ReactTestRenderer;
    await act(async () => { screen = renderer.create(<ArTryOnScreen />); });
    await act(async () => { screen.root.findByProps({ accessibilityLabel: 'ar.arc.tools' }).props.onPress(); });
    expect(filterChips(screen)).toEqual(expect.arrayContaining(['ar.texture.matte', 'ar.texture.cream', 'ar.texture.glossy', 'ar.texture.shimmer', 'ar.chip.lipCare']));
    expect(filterChips(screen).some((label) => label.startsWith('ar.family.'))).toBe(true);
    await act(async () => { screen.unmount(); });
  });

  it('groups velvet with matte, satin with cream, sheer with glossy and leaves lip skincare out', async () => {
    let screen!: renderer.ReactTestRenderer;
    await act(async () => { screen = renderer.create(<ArTryOnScreen />); });
    await act(async () => { screen.root.findByProps({ accessibilityLabel: 'ar.arc.tools' }).props.onPress(); });
    expect(swatch(screen, 'essence')).toBeUndefined();
    expect(swatch(screen, 'oil')).toBeUndefined();
    const matte = screen.root.findAllByType(Chip).find((c) => c.props.label === 'ar.texture.matte')!;
    await act(async () => { matte.props.onPress(); });
    expect(swatch(screen, 'matte')).toBeDefined();
    expect(swatch(screen, 'velvet')).toBeDefined();
    expect(swatch(screen, 'satin')).toBeUndefined();
    await act(async () => { screen.unmount(); });
  });

  it('opens 립오일·립밤 only inside 립케어', async () => {
    let screen!: renderer.ReactTestRenderer;
    await act(async () => { screen = renderer.create(<ArTryOnScreen />); });
    await act(async () => { screen.root.findByProps({ accessibilityLabel: 'ar.arc.tools' }).props.onPress(); });
    const care = screen.root.findAllByType(Chip).find((c) => c.props.label === 'ar.chip.lipCare')!;
    await act(async () => { care.props.onPress(); });
    expect(filterChips(screen)).toEqual([
      'ar.filter.all', 'ar.texture.matte', 'ar.texture.cream', 'ar.texture.glossy', 'ar.texture.shimmer', 'ar.chip.lipCare', 'ar.care.oil', 'ar.care.balm',
    ]);
    expect(swatch(screen, 'oil')).toBeDefined();
    expect(swatch(screen, 'balm')).toBeDefined();
    expect(swatch(screen, 'matte')).toBeUndefined();
    await act(async () => { screen.unmount(); });
  });

  it('takes a worn colour off when it is pressed again', async () => {
    let screen!: renderer.ReactTestRenderer;
    await act(async () => { screen = renderer.create(<ArTryOnScreen />); });
    await act(async () => { swatch(screen, 'matte')!.props.onPress(); });
    expect(useMakeupStore.getState().makeup.lip?.hex).toBe('#B3202E');
    await act(async () => { swatch(screen, 'matte')!.props.onPress(); });
    expect(useMakeupStore.getState().makeup.lip).toBeNull();
    await act(async () => { screen.unmount(); });
  });
});
