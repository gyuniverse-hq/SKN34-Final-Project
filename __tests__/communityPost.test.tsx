import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import renderer, { act } from 'react-test-renderer';
import { TextInput } from 'react-native';
import CommunityPost from '@/app/community-post';
import { BottomSheet } from '@/components/ui/BottomSheet';
import { Button } from '@/components/ui/Button';
import { communityFeedHref, LOOK_COMMUNITY } from '@/lib/lookCommunity';

const mockDismissTo = jest.fn();
const mockGet = jest.fn();
const mockPost = jest.fn();
const path = `${LOOK_COMMUNITY}/rose-look`;
const post = { id: 'rose-look', title: 'Rose look', votes: 2, products: [] };

jest.mock('expo-router', () => ({
  Stack: {
    Screen: ({ options }: { options: { headerLeft: () => React.ReactNode; headerRight?: () => React.ReactNode } }) => (
      <>{options.headerLeft()}{options.headerRight?.()}</>
    ),
  },
  useLocalSearchParams: () => ({ id: 'rose-look' }),
  useRouter: () => ({ dismissTo: mockDismissTo }),
}));
jest.mock('@expo/vector-icons/Ionicons', () => 'Ionicons');
jest.mock('expo-image', () => ({ Image: 'ExpoImage' }));
jest.mock('react-native-safe-area-context', () => ({ SafeAreaView: 'SafeAreaView', useSafeAreaInsets: () => ({ bottom: 0 }) }));
jest.mock('@/lib/i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }));
jest.mock('@/lib/auth', () => ({ useAuth: () => ({ user: { id: 'member' } }) }));
jest.mock('@/lib/api', () => ({
  ApiError: class extends Error {},
  API_BASE_URL: '',
  apiGet: (...args: unknown[]) => mockGet(...args),
  apiPost: (...args: unknown[]) => mockPost(...args),
}));
jest.mock('@/lib/queries', () => ({ useProductsByIds: () => ({ data: [] }) }));

test('detail actions return to the feed, record a recommendation, and retry a failed report in the sheet', async () => {
  const viewer = { owned: false, recommended: false, reported: false };
  mockGet.mockImplementation(async (url: string) => url.endsWith('/viewer') ? viewer : post);
  mockPost.mockResolvedValueOnce({ ...post, votes: 3 }).mockRejectedValueOnce(new Error('Offline'))
    .mockResolvedValueOnce({ ...post, votes: 3 });
  const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } });
  queryClient.setQueryData(['look-community', 'viewer', post.id, 'member'], viewer);
  queryClient.setQueryData(['look-community', 'post', post.id], post);
  let screen!: renderer.ReactTestRenderer;

  try {
    await act(async () => {
      screen = renderer.create(<QueryClientProvider client={queryClient}><CommunityPost /></QueryClientProvider>);
    });
    const button = (label: string) => screen.root.findAllByType(Button).find(node => node.props.label === label)!;
    const flag = (label: string) => screen.root.findAll(node =>
      node.props.accessibilityLabel === label && typeof node.props.onPress === 'function')[0];

    await act(async () => { button('community.backToFeed').props.onPress(); });
    expect(mockDismissTo).toHaveBeenCalledWith(communityFeedHref);
    await act(async () => { button('community.recommend').props.onPress(); });
    expect(mockPost).toHaveBeenLastCalledWith(`${path}/recommend`, {}, { expectedUserId: 'member' });
    expect(queryClient.getQueryData(['look-community', 'post', post.id])).toMatchObject({ votes: 3 });

    await act(async () => { flag('community.report').props.onPress(); });
    expect(screen.root.findByType(BottomSheet)).toBeTruthy();
    expect(button('community.recommended').props.disabled).toBe(true);
    expect(button('community.report').props.disabled).toBe(true);
    await act(async () => { screen.root.findByType(TextInput).props.onChangeText('  Not a makeup look  '); });
    await act(async () => { button('community.report').props.onPress(); });
    expect(mockPost).toHaveBeenLastCalledWith(`${path}/report`, { reason: 'Not a makeup look' }, { expectedUserId: 'member' });
    expect(screen.root.findByType(TextInput).props.value).toBe('  Not a makeup look  ');
    expect(screen.root.findAll(node => node.props.accessibilityRole === 'alert' && node.props.children === 'community.error')).not.toHaveLength(0);
    await act(async () => { button('community.report').props.onPress(); });
    expect(screen.root.findAllByType(BottomSheet)).toHaveLength(0);
    expect(flag('community.reported').props.disabled).toBe(true);
  } finally {
    await act(async () => { screen.unmount(); });
    queryClient.clear();
  }
});
