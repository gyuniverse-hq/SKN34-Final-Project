import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import renderer, { act } from 'react-test-renderer';
import CommunityWrite from '@/app/community-write';
import { Button } from '@/components/ui/Button';

const mockUpload = jest.fn();
const mockPick = jest.fn();
const mockReplace = jest.fn();
const mockPreparePhoto = jest.fn();

jest.mock('expo-router', () => ({
  Stack: { Screen: () => null },
  useLocalSearchParams: () => ({ title: 'Rose look', products: '[{"productId":"lip-1","shadeId":"rose"}]' }),
  useRouter: () => ({ replace: mockReplace }),
}));
jest.mock('expo', () => ({ ...jest.requireActual('expo'), uuid: { v4: () => 'new-post' } }));
jest.mock('@expo/vector-icons/Ionicons', () => 'Ionicons');
jest.mock('expo-image-picker', () => ({ launchImageLibraryAsync: () => mockPick() }));
jest.mock('expo-image', () => ({ Image: 'ExpoImage' }));
jest.mock('react-native-safe-area-context', () => ({ SafeAreaView: 'SafeAreaView' }));
jest.mock('@/lib/i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }));
jest.mock('@/lib/auth', () => ({ useAuth: () => ({ user: { id: 'member' } }) }));
jest.mock('@/lib/api', () => ({ API_BASE_URL: '', apiForm: (...args: unknown[]) => mockUpload(...args) }));
jest.mock('@/lib/lookCommunityPhoto', () => ({
  prepareCommunityPhoto: (photo: unknown) => mockPreparePhoto(photo),
}));
jest.mock('@/hooks/useDebouncedValue', () => ({ useDebouncedValue: (value: string) => value }));
jest.mock('@/lib/queries', () => {
  const product = { id: 'cheek-1', name: 'Peach Blush', brand: 'Beauty', category: 'cheek' };
  return {
    useProducts: (_params: unknown, enabled: boolean) => ({ data: enabled ? [product] : [] }),
    useProductsByIds: (ids: string[]) => ({ data: ids.includes(product.id) ? [product] : [] }),
  };
});

afterEach(() => jest.restoreAllMocks());

test('an AR-prefilled post uploads the gallery photo only after preview and consent', async () => {
  const append = jest.spyOn(FormData.prototype, 'append');
  mockPick
    .mockResolvedValueOnce({ canceled: false, assets: [{ uri: 'file:///large.jpg', fileSize: 3 * 1024 * 1024 }] })
    .mockResolvedValueOnce({ canceled: false, assets: [{ uri: 'file:///original.jpg', fileSize: 3 * 1024 * 1024 }] });
  mockPreparePhoto
    .mockResolvedValueOnce(null)
    .mockResolvedValueOnce({ uri: 'file:///chosen.jpg', mimeType: 'image/jpeg', fileSize: 500_000 });
  mockUpload.mockResolvedValue({ id: 'new-post' });
  const queryClient = new QueryClient();
  let screen!: renderer.ReactTestRenderer;
  await act(async () => {
    screen = renderer.create(<QueryClientProvider client={queryClient}><CommunityWrite /></QueryClientProvider>);
  });
  const button = (label: string) => screen.root.findAllByType(Button).find(node => node.props.label === label)!;
  const photoButton = (label: string) => screen.root.findAll(node =>
    node.props.accessibilityLabel === label && typeof node.props.onPress === 'function')[0];
  const photoUri = () => screen.root.findAll(node => node.props.accessibilityLabel === 'community.photo')[0].props.source.uri;
  expect(button('community.review').props.disabled).toBe(true);
  expect(button('community.review').props.accessibilityHint).toBe('community.photoNeeded');
  await act(async () => {
    photoButton('community.pickPhoto').props.onPress();
  });
  expect(photoUri()).toBe('file:///large.jpg');
  expect(screen.root.findAll(node =>
    node.props.accessibilityRole === 'alert' && node.props.children === 'community.photoSize')).not.toHaveLength(0);
  expect(button('community.review').props.disabled).toBe(true);
  await act(async () => {
    photoButton('community.changePhoto').props.onPress();
    screen.root.findAll(node => node.props.accessibilityLabel === 'community.displayName' && typeof node.props.onChangeText === 'function')[0].props.onChangeText('Rose Studio');
  });
  expect(photoUri()).toBe('file:///chosen.jpg');
  expect(mockPreparePhoto).toHaveBeenLastCalledWith(expect.objectContaining({ uri: 'file:///original.jpg' }));
  const fields = screen.root.findAll(node => typeof node.props.onChangeText === 'function' &&
    ['community.searchProducts', 'community.title'].includes(node.props.accessibilityLabel));
  expect(fields[0].props.accessibilityLabel).toBe('community.searchProducts');
  await act(async () => { fields[0].props.onChangeText('Peach'); });
  await act(async () => { button('community.add').props.onPress(); });
  expect(button('community.review').props.disabled).toBe(false);
  expect(mockUpload).not.toHaveBeenCalled();
  await act(async () => { button('community.review').props.onPress(); });
  expect(screen.root.findAll(node => node.props.children === 'Peach Blush')).not.toHaveLength(0);
  expect(button('community.publish').props.disabled).toBe(true);
  await act(async () => { button('community.publish').props.onPress(); });
  expect(mockUpload).not.toHaveBeenCalled();
  await act(async () => {
    screen.root.findAll(node => node.props.accessibilityRole === 'checkbox' && typeof node.props.onPress === 'function')[0].props.onPress();
  });
  await act(async () => { button('community.publish').props.onPress(); });
  expect(mockUpload).toHaveBeenCalledTimes(1);
  const [path, method, , owner] = mockUpload.mock.calls[0];
  expect([path, method, owner]).toEqual(['/api/look-community/new-post', 'POST', 'member']);
  expect(append).toHaveBeenCalledWith('image', expect.objectContaining({ uri: 'file:///chosen.jpg' }));
  expect(append).toHaveBeenCalledWith('consent', 'true');
  expect(append).toHaveBeenCalledWith('content', expect.stringContaining('"shadeId":"rose"'));
  expect(append).toHaveBeenCalledWith('content', expect.stringContaining('"productId":"cheek-1"'));
  expect(append).toHaveBeenCalledWith('content', expect.stringContaining('"displayName":"Rose Studio"'));
  expect(mockReplace).toHaveBeenCalledWith({ pathname: '/community-post', params: { id: 'new-post' } });
  await act(async () => { screen.unmount(); });
  queryClient.clear();
});
