import AsyncStorage from '@react-native-async-storage/async-storage';
import { useEffect } from 'react';
import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import HomeScreen from '@/app/(tabs)/index';
import { SkinMatchSection } from '@/components/skin/SkinMatchSection';
import { useFirstArExit } from '@/hooks/useFirstArExit';
import { useSkinMatchedProducts } from '@/hooks/useSkinMatchedProducts';
import { apiPost } from '@/lib/api';
import { offerAction } from '@/lib/confirm';
import { useProducts } from '@/lib/queries';
import { readSkinProfile } from '@/lib/skinProfile';
import type { SkinProfile } from '@/types/skin';

const mockPush = jest.fn();
const mockReplace = jest.fn();
let mockOwner: string | null = null;
let mockProfile: SkinProfile | null = null;
let mockSubscribed = false;
jest.mock('expo-router', () => ({
  useRouter: () => ({ replace: mockReplace, push: mockPush }),
  useFocusEffect: (cb: () => () => void) => require('react').useEffect(cb, [cb]),
}));
jest.mock('@/lib/i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }));
jest.mock('@/lib/auth', () => ({ getCurrentUserId: async () => mockOwner }));
jest.mock('@/lib/api', () => ({ apiPost: jest.fn() }));
jest.mock('@/lib/skinAnalysis', () => ({ skinAnalysisSupported: true }));
jest.mock('@/lib/skinProfile', () => ({ readSkinProfile: jest.fn() }));
jest.mock('@/lib/confirm', () => ({ offerAction: jest.fn() }));
jest.mock('@/hooks/useOwnedSkinProfile', () => ({ useOwnedSkinProfile: () => ({ profile: mockProfile }) }));
jest.mock('@/hooks/useSkinAccess', () => ({ useSkinAccess: () => ({ ready: true, subscribed: mockSubscribed }) }));
jest.mock('@/lib/queries', () => ({
  useProducts: jest.fn(() => ({ data: [] })), useStyleLooks: () => ({ data: [] }),
}));
jest.mock('@expo/vector-icons/Ionicons', () => 'Ionicons');
jest.mock('@expo/vector-icons/MaterialCommunityIcons', () => 'MaterialCommunityIcons');
jest.mock('react-native-safe-area-context', () => ({ SafeAreaView: 'SafeAreaView' }));
jest.mock('@/components/celeb/KStyleCollection', () => ({ KStyleCollection: 'Collection' }));
jest.mock('@/components/home/HomeCatalog', () => ({ HomeCategories: 'Categories', HomeProductSection: 'ProductSection' }));
jest.mock('@/components/home/HomeSearch', () => ({ HomeSearch: 'HomeSearch' }));
jest.mock('@/components/shop/ShopHeaderActions', () => ({ ShopHeaderActions: 'HeaderActions' }));
jest.mock('@/lib/skinFilters', () => ({ suggestConcerns: () => ['dryness'] }));

let tree: ReactTestRenderer;
let exit: ReturnType<typeof useFirstArExit>;
let home: ReturnType<typeof useSkinMatchedProducts>;
function Probe() {
  const onExit = useFirstArExit();
  const match = useSkinMatchedProducts();
  useEffect(() => { exit = onExit; home = match; });
  return null;
}
async function visit() { await act(async () => { tree = create(<Probe />); }); }
beforeEach(async () => {
  jest.clearAllMocks();
  await AsyncStorage.clear();
  mockOwner = null;
  mockProfile = null;
  mockSubscribed = false;
  jest.mocked(readSkinProfile).mockResolvedValue(null);
});
afterEach(async () => { await act(async () => { tree?.unmount(); }); });

it('offers analysis once to a first-time AR guest, and opens consent on acceptance', async () => {
  const leave = jest.fn();
  jest.mocked(offerAction).mockImplementationOnce((_message, _yes, _no, accept) => accept());
  await visit();
  await exit(leave);
  expect(mockReplace).toHaveBeenCalledWith('/skin-consent');
  await act(async () => { tree.unmount(); });
  await visit();
  await exit(leave);
  expect(offerAction).toHaveBeenCalledTimes(1);
  expect(leave).toHaveBeenCalledTimes(1);
});

it('skips the AR prompt when analysis happened on this device or the account already used AR or analysis', async () => {
  const leave = jest.fn();
  jest.mocked(readSkinProfile).mockResolvedValue({} as SkinProfile);
  await visit();
  await exit(leave);
  await act(async () => { tree.unmount(); });
  mockOwner = 'returning';
  jest.mocked(readSkinProfile).mockResolvedValue(null);
  jest.mocked(apiPost).mockResolvedValue(false);
  await visit();
  await exit(leave);
  expect(offerAction).not.toHaveBeenCalled();
  expect(leave).toHaveBeenCalledTimes(2);
});

it.each([[false, false], [false, true], [true, false], [true, true]])(
  'only loads recommendation products with a local report (%s) and subscription (%s)', async (analyzed, subscribed) => {
    mockProfile = analyzed ? {} as SkinProfile : null;
    mockSubscribed = subscribed;
    await visit();
    expect(home.visible).toBe(analyzed && subscribed);
    expect(Boolean(home.needsSubscription)).toBe(analyzed && !subscribed);
    expect(useProducts).toHaveBeenCalledWith({ category: 'skincare', concerns: ['dryness'] }, analyzed && subscribed);
  });

it.each([
  [false, 'skinAccess.afterAnalysis', '/skin-consent'],
  [true, 'skinAccess.afterJoin', '/membership'],
] as const)('keeps the home entry visible with the appropriate action (analyzed %s)', async (analyzed, message, path) => {
  mockProfile = analyzed ? {} as SkinProfile : null;
  await act(async () => { tree = create(<HomeScreen />); });
  const section = tree.root.findByType(SkinMatchSection);
  expect(section.props.availability).toBe(message);
  expect(section.findAllByProps({ children: message }).length).toBeGreaterThan(0);
  const action = section.findAll(node => node.props.accessibilityRole === 'button' && typeof node.props.onPress === 'function')[0];
  action.props.onPress();
  expect(mockPush).toHaveBeenCalledWith(path);
});
