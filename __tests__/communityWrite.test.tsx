import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import renderer, { act } from 'react-test-renderer';
import CommunityWrite from '@/app/community-write';
import { Button } from '@/components/ui/Button';

const mockUpload = jest.fn();
const mockPick = jest.fn();
const mockReplace = jest.fn();

jest.mock('expo-router', () => ({
  Stack: { Screen: () => null },
  useLocalSearchParams: () => ({ title: 'Rose look', products: '[{"productId":"lip-1","shadeId":"rose"}]' }),
  useRouter: () => ({ replace: mockReplace }),
}));
jest.mock('expo', () => ({ ...jest.requireActual('expo'), uuid: { v4: () => 'new-post' } }));
jest.mock('expo-image-picker', () => ({ launchImageLibraryAsync: () => mockPick() }));
jest.mock('expo-image', () => ({ Image: 'ExpoImage' }));
jest.mock('react-native-safe-area-context', () => ({ SafeAreaView: 'SafeAreaView' }));
jest.mock('@/lib/i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }));
jest.mock('@/lib/auth', () => ({ useAuth: () => ({ user: { id: 'member' } }) }));
jest.mock('@/lib/api', () => ({ API_BASE_URL: '', apiForm: (...args: unknown[]) => mockUpload(...args) }));
jest.mock('@/lib/queries', () => ({ useProducts: () => ({}), useProductsByIds: () => ({}) }));

afterEach(() => jest.restoreAllMocks());

test('an AR-prefilled post uploads the gallery photo only after preview and consent', async () => {
  const append = jest.spyOn(FormData.prototype, 'append');
  mockPick.mockResolvedValue({ canceled: false, assets: [{ uri: 'file:///chosen.jpg', mimeType: 'image/jpeg' }] });
  mockUpload.mockResolvedValue({ id: 'new-post' });
  const queryClient = new QueryClient();
  let screen!: renderer.ReactTestRenderer;
  await act(async () => {
    screen = renderer.create(<QueryClientProvider client={queryClient}><CommunityWrite /></QueryClientProvider>);
  });
  const button = (label: string) => screen.root.findAllByType(Button).find(node => node.props.label === label)!;
  expect(button('community.review').props.disabled).toBe(true);
  await act(async () => { button('community.pickPhoto').props.onPress(); });
  expect(mockUpload).not.toHaveBeenCalled();
  await act(async () => { button('community.review').props.onPress(); });
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
  expect(mockReplace).toHaveBeenCalledWith({ pathname: '/community-post', params: { id: 'new-post' } });
  await act(async () => { screen.unmount(); });
  queryClient.clear();
});
