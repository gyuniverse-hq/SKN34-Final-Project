import { Text, TextInput } from 'react-native';
import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import { HomeSearch } from '@/components/home/HomeSearch';
import { useRecentSearchStore } from '@/store/recentSearchStore';

jest.mock('@expo/vector-icons/Ionicons', () => 'Ionicons');
jest.mock('expo-router', () => ({
  useFocusEffect: (callback: () => void | (() => void)) => require('react').useEffect(callback, [callback]),
}));
jest.mock('@/lib/i18n', () => ({
  useI18n: () => ({ t: (key: string, params?: { query: string }) => params ? key + ':' + params.query : key }),
}));

let screen: ReactTestRenderer;
const search = jest.fn();
const input = () => screen.root.findByType(TextInput);
const recent = () => screen.root.findAllByType(Text).some(node => node.props.children === 'discovery.recent');
const tap = async (label: string) => {
  const button = screen.root.findAll(node => node.props.accessibilityLabel === label && typeof node.props.onPress === 'function')[0];
  await act(async () => { button.props.onPress(); });
};

beforeEach(async () => {
  search.mockClear();
  useRecentSearchStore.getState().clear();
  await act(async () => { screen = create(<HomeSearch onSearch={search}><Text>feed</Text></HomeSearch>); });
});
afterEach(async () => { await act(async () => { screen.unmount(); }); });

it('keeps focus on home until submission and saves the trimmed search for reuse', async () => {
  await act(async () => { input().props.onFocus(); });
  expect(recent()).toBe(false);
  await act(async () => { input().props.onChangeText('  립틴트  '); });
  expect(search).not.toHaveBeenCalled();
  await act(async () => { input().props.onSubmitEditing(); });
  expect(search).toHaveBeenCalledWith('립틴트');
  expect(useRecentSearchStore.getState().searches).toEqual(['립틴트']);
  expect(recent()).toBe(false);
  await act(async () => { input().props.onFocus(); });
  expect(recent()).toBe(true);
  await tap('립틴트');
  expect(search).toHaveBeenCalledTimes(2);
  expect(recent()).toBe(false);
});

it('allows individual deletion and dismisses history without navigating', async () => {
  await act(async () => {
    useRecentSearchStore.getState().add('쿠션');
    useRecentSearchStore.getState().add('립');
    input().props.onFocus();
  });
  await tap('discovery.removeSearch:립');
  expect(useRecentSearchStore.getState().searches).toEqual(['쿠션']);
  expect(recent()).toBe(true);
  await act(async () => { input().props.onChangeText('로션'); });
  expect(recent()).toBe(false);
  await tap('home.clearQuery');
  expect(recent()).toBe(true);
  await act(async () => { input().props.onKeyPress({ nativeEvent: { key: 'Escape' } }); });
  expect(recent()).toBe(false);
  expect(search).not.toHaveBeenCalled();
});
