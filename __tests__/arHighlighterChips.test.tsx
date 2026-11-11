import React from 'react';
import renderer, { act } from 'react-test-renderer';
import ArTryOnScreen from '@/app/(tabs)/ar';
import { Chip } from '@/components/ui/Chip';
import { HL_FACE_AREAS } from '@/lib/arFacePalette';
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
jest.mock('@/hooks/useArRouteSelection', () => ({ useArRouteSelection: () => ({ product: { data: { makeupZone: 'highlighter' } } }) }));
jest.mock('@/lib/queries', () => {
  const products = [{
    id: 'hl', brand: 'B', name: '하이라이터', nameKo: '하이라이터', category: 'highlighter', makeupZone: 'highlighter', texture: 'satin',
    priceKRW: 0, volume: '', description: '', keyIngredients: [], tags: [], imageUrl: '', searchKeyword: '',
    shades: [{ id: 's', name: 'hl', hex: '#F5E1C4' }],
  }];
  return { useProducts: () => ({ data: products }), useTryOnProducts: () => ({ data: products }) };
});

const chip = (screen: renderer.ReactTestRenderer, label: string) =>
  screen.root.findAllByType(Chip).find((c) => c.props.label === label)!;
const areasOn = (screen: renderer.ReactTestRenderer) =>
  screen.root.findAllByType(Chip).filter((c) => String(c.props.label).startsWith('looks.area.') && c.props.selected)
    .map((c) => String(c.props.label).replace('looks.area.', ''));

describe('AR highlighter chips (11-11: face type sets the regions, chips show what is painted)', () => {
  beforeEach(() => {
    useMakeupStore.getState().reset();
    useMakeupStore.setState((s) => ({ makeup: { ...s.makeup, highlighter: { hex: '#F5E1C4', intensity: 0.8, texture: 'satin' } } }));
  });

  it('shows the oval set before any measurement and the picked face type set after a face chip', async () => {
    let screen!: renderer.ReactTestRenderer;
    await act(async () => { screen = renderer.create(<ArTryOnScreen />); });
    expect(chip(screen, 'ar.hlFace.auto').props.selected).toBe(true);
    expect(areasOn(screen)).toEqual(HL_FACE_AREAS.oval);
    await act(async () => { chip(screen, 'ar.faceShape.name.oblong').props.onPress(); });
    expect(useMakeupStore.getState().makeup.highlighter?.geometry?.hlFace).toBe('oblong');
    expect(areasOn(screen)).toEqual(HL_FACE_AREAS.oblong);
    // A region chip changes only that region; pressing the face chip again goes back to auto.
    await act(async () => { chip(screen, 'looks.area.philtrum').props.onPress(); });
    expect(areasOn(screen)).toEqual(HL_FACE_AREAS.oblong.filter((a) => a !== 'philtrum'));
    await act(async () => { chip(screen, 'ar.faceShape.name.oblong').props.onPress(); });
    expect(useMakeupStore.getState().makeup.highlighter?.geometry?.hlFace).toBeUndefined();
    expect(areasOn(screen)).toEqual(HL_FACE_AREAS.oval);
    await act(async () => { screen.unmount(); });
  });

  it('shows no region while a style template is drawn, and a region chip turns the style off', async () => {
    let screen!: renderer.ReactTestRenderer;
    await act(async () => { screen = renderer.create(<ArTryOnScreen />); });
    await act(async () => { chip(screen, 'ar.hlStyle.natural_cheek').props.onPress(); });
    expect(areasOn(screen)).toEqual([]);
    expect(chip(screen, 'ar.hlFace.auto').props.selected).toBe(false);
    await act(async () => { chip(screen, 'looks.area.chin').props.onPress(); });
    const g = useMakeupStore.getState().makeup.highlighter?.geometry;
    expect(g?.hlStyle).toBeUndefined();
    expect(areasOn(screen)).toContain('chin');
    await act(async () => { screen.unmount(); });
  });
});
