import renderer, { act } from 'react-test-renderer';
import ArTryOnScreen from '@/app/(tabs)/ar';
import { CoverageBar } from '@/components/ar/CoverageBar';
import { OpenArcPalette } from '@/components/ar/OpenArcPalette';
import { ArSheet } from '@/components/ar/ArSheet';
import { NearbyExplorer } from '@/components/ar/NearbyExplorer';
import { Button } from '@/components/ui/Button';
import { Chip } from '@/components/ui/Chip';
import { useMakeupStore } from '@/store/makeupStore';
import type { Product } from '@/types';

const mockSource: Product = {
  id: 'source', brand: 'Hince', name: 'Lip', nameKo: '립', category: 'lip', makeupZone: 'lip', texture: 'matte',
  priceKRW: 0, volume: '', description: '', keyIngredients: [], tags: [], imageUrl: '', searchKeyword: '',
  shades: [{ id: 's', name: 'Source', hex: '#BE636A' }],
};
const mockCandidate: Product = { ...mockSource, id: 'candidate', texture: 'glossy',
  shades: [{ id: 'c', name: 'Candidate', hex: '#C2636B' }] };
const mockBlush: Product = { ...mockSource, id: 'blush', makeupZone: 'blush', texture: 'cream' };
const mockBlushCandidate: Product = { ...mockCandidate, id: 'blush-candidate', makeupZone: 'blush' };
const mockProducts = [mockSource, mockCandidate, mockBlush, mockBlushCandidate];
let mockRouteProduct: Product | undefined;

jest.mock('react-native-safe-area-context', () => ({
  ...jest.requireActual('react-native-safe-area-context'),
  useSafeAreaInsets: () => ({ top: 0, right: 0, bottom: 0, left: 0 }),
}));
jest.mock('@expo/vector-icons/Ionicons', () => 'Ionicons');
jest.mock('expo-camera', () => ({ useCameraPermissions: () => [{ granted: false, canAskAgain: true }, jest.fn()] }));
jest.mock('expo-haptics', () => ({ selectionAsync: jest.fn(() => Promise.resolve()) }));
jest.mock('expo-router', () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), canGoBack: () => false }),
  useLocalSearchParams: () => mockRouteProduct ? { productId: mockRouteProduct.id, shadeId: mockRouteProduct.shades[0].id } : {},
  useNavigation: () => ({ setOptions: jest.fn() }), useFocusEffect: jest.fn(),
}));
jest.mock('expo-linear-gradient', () => ({ LinearGradient: 'LinearGradient' }));
jest.mock('@/components/ar/ArFaceView', () => ({ ArFaceView: 'ArFaceView' }));
jest.mock('@/lib/i18n', () => ({ useI18n: () => ({ t: (key: string) => key, language: 'ko' }) }));
jest.mock('@/hooks/useArRouteSelection', () => ({ useArRouteSelection: () => ({ product: { data: mockRouteProduct } }) }));
jest.mock('@/lib/queries', () => ({ useTryOnProducts: () => ({ data: mockProducts }) }));

it('connects mode tabs, preview, rebase, restore and free mode without losing the lip shape or finish', async () => {
  useMakeupStore.getState().reset();
  useMakeupStore.getState().applyShade(mockSource, mockSource.shades[0]);
  useMakeupStore.getState().patchGeometry('lip', { overlip: 0.2 });
  useMakeupStore.getState().setIntensity('lip', 0.6);
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<ArTryOnScreen />); });
  const explorer = () => screen.root.findByType(NearbyExplorer);
  expect(screen.root.findAllByType(Button).some((p) => ['ar.similar', 'ar.recommendColor'].includes(p.props.label))).toBe(false);
  const tab = (key: string) => {
    const found = screen.root.findAllByProps({ accessibilityRole: 'tab' }).find((p) =>
      p.findAllByProps({ children: key }).length);
    if (!found) throw new Error(`Missing tab: ${key}`);
    return found;
  };
  const openTools = async () => { await act(async () => { screen.root.findByProps({ accessibilityLabel: 'ar.arc.tools' }).props.onPress(); }); };
  const closeTools = async () => { await act(async () => { screen.root.findByType(ArSheet).props.onClose(); }); };
  await openTools();
  // A color-family selection remains a free-mode filter, never a hidden nearby restriction.
  const family = screen.root.findAllByType(Chip).find((p) => p.props.label.startsWith('ar.family.'))!;
  expect(family).toBeDefined();
  const familyLabel = family.props.label;
  await act(async () => { family.props.onPress(); });
  await closeTools();
  await act(async () => { screen.root.findByProps({ accessibilityLabel: 'ar.explore.nearby' }).props.onPress(); });
  await openTools();
  expect(explorer().props.active).toBe(true);
  expect(screen.root.findAllByType(Chip).some((p) => p.props.label.startsWith('ar.family.'))).toBe(false);
  expect(explorer().props.counts.similar).toBe(1);
  await act(async () => {
    screen.root.findAllByType(Chip).find((p) => p.props.label === 'ar.texture.matte')!.props.onPress();
  });
  expect(explorer().props.counts.similar).toBe(0);
  await closeTools();
  expect(screen.root.findAllByProps({ children: 'ar.explore.empty' }).length).toBeGreaterThan(0);
  await openTools();
  await act(async () => {
    screen.root.findAllByType(Chip).find((p) => p.props.label === 'ar.explore.allTextures')!.props.onPress();
  });
  expect(explorer().props.counts.similar).toBe(1);
  await closeTools();
  const chip = screen.root.findAllByProps({ accessibilityLabel: 'Hince Lip Candidate' })[0];
  expect(chip).toBeDefined();
  await act(async () => { chip.props.onPress(); });
  expect(useMakeupStore.getState().makeup.lip).toMatchObject({
    hex: '#C2636B', texture: 'glossy', intensity: 0.6, geometry: { overlip: 0.2 },
  });
  expect(explorer().props.anchor.product.id).toBe('source');
  await act(async () => {
    screen.root.findByProps({ accessibilityLabel: 'ar.explore.rebase' }).props.onPress();
  });
  expect(explorer().props.anchor.product.id).toBe('candidate');
  await act(async () => {
    screen.root.findByProps({ accessibilityLabel: 'ar.explore.back' }).props.onPress();
  });
  expect(explorer().props.anchor.product.id).toBe('source');
  await act(async () => { explorer().props.onApplyAnchor(); });
  expect(useMakeupStore.getState().selections.lip?.productId).toBe('source');
  await act(async () => { screen.root.findByProps({ accessibilityLabel: 'ar.explore.free' }).props.onPress(); });
  await openTools();
  expect(explorer().props.active).toBe(false);
  expect(screen.root.findAllByType(Chip).find((p) => p.props.label === familyLabel)?.props.selected).toBe(true);
  await act(async () => { tab('ar.zone.eyeshadow').props.onPress(); });
  expect(screen.root.findAllByType(NearbyExplorer)).toHaveLength(0);
  expect(screen.root.findAllByType(Button).some((p) => p.props.label === 'ar.recommendColor')).toBe(true);
  await act(async () => { screen.unmount(); });
});

it('clears a lip finish filter when a product route opens blush, so there is no hidden filter', async () => {
  useMakeupStore.getState().reset();
  useMakeupStore.getState().applyShade(mockSource, mockSource.shades[0]);
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<ArTryOnScreen />); });
  try {
    await act(async () => { screen.root.findByProps({ accessibilityLabel: 'ar.arc.tools' }).props.onPress(); });
    await act(async () => {
      screen.root.findAllByType(Chip).find((p) => p.props.label === 'ar.texture.matte')!.props.onPress();
      screen.root.findByType(NearbyExplorer).props.onEnter();
    });
    await act(async () => {
      mockRouteProduct = mockBlush;
      useMakeupStore.getState().applyShade(mockBlush, mockBlush.shades[0]);
    });
    expect(screen.root.findByType(NearbyExplorer).props.active).toBe(false);
    await act(async () => { screen.root.findByType(NearbyExplorer).props.onEnter(); });
    expect(screen.root.findByType(NearbyExplorer).props.anchor.product.id).toBe('blush');
    expect(screen.root.findByType(NearbyExplorer).props.counts.similar).toBe(1);
  } finally {
    await act(async () => { screen.unmount(); });
    mockRouteProduct = undefined;
  }
});


it('keeps manual adjustments inside direct exploration and preserves them through chat mode', async () => {
  useMakeupStore.getState().reset();
  useMakeupStore.getState().applyShade(mockSource, mockSource.shades[0]);
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<ArTryOnScreen />); });
  expect(screen.root.findAllByType(CoverageBar)).toHaveLength(0);
  await act(async () => { screen.root.findByProps({ accessibilityLabel: 'ar.arc.tools' }).props.onPress(); });
  await act(async () => { screen.root.findByType(CoverageBar).props.onChange(0.35); });
  expect(useMakeupStore.getState().makeup.lip?.intensity).toBe(0.35);
  await act(async () => { screen.root.findByType(ArSheet).props.onClose(); });
  const modeTab = (key: string) => screen.root.findAllByProps({ accessibilityRole: 'tab' }).find((p) => p.findAllByProps({ children: key }).length)!;
  await act(async () => { modeTab('ar.mode.chat').props.onPress(); });
  expect(screen.root.findAllByProps({ accessibilityLabel: 'ar.arc.tools' })).toHaveLength(0);
  expect(screen.root.findAllByType(CoverageBar)).toHaveLength(0);
  expect(screen.root.findAllByType(OpenArcPalette)).toHaveLength(0);
  expect(screen.root.findAllByProps({ accessibilityLabel: 'ar.send' }).length).toBeGreaterThan(0);
  await act(async () => { modeTab('ar.mode.direct').props.onPress(); });
  expect(screen.root.findByType(OpenArcPalette)).toBeTruthy();
  expect(useMakeupStore.getState().makeup.lip?.intensity).toBe(0.35);
  expect(useMakeupStore.getState().selections.lip).toEqual({ productId: 'source', shadeId: 's' });
  await act(async () => { screen.unmount(); });
});
