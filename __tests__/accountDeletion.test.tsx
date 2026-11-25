import AsyncStorage from '@react-native-async-storage/async-storage';
import type { QueryClient } from '@tanstack/react-query';
import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import RootLayout from '@/app/_layout';
import mockSettingsScreen from '@/app/settings';
import { Button } from '@/components/ui/Button';
import { ApiError, apiDelete } from '@/lib/api';
import { signOut } from '@/lib/auth';
import { skinProfileKey } from '@/lib/skinProfile';
import { pendingProfileKey } from '@/lib/skinRegistration';
import { chatRequestRecoveryKey, chatRoomDeletionKey, STORAGE_KEYS } from '@/lib/storage';
import { useChatConversationStore } from '@/store/chatConversationStore';

let mockOwner: string | null;
let mockConfirm: (() => void) | undefined;
let mockClient: QueryClient;
const mockMemorySettings = jest.fn(async () => undefined);

jest.mock('expo-font', () => ({ useFonts: () => [true, null], isLoaded: () => true }));
jest.mock('@expo/vector-icons/Ionicons', () => () => null);
jest.mock('expo-router/head', () => ({ __esModule: true, default: () => null }));
jest.mock('expo-splash-screen', () => ({
  preventAutoHideAsync: async () => {},
  hideAsync: async () => {},
}));
jest.mock('react-native-safe-area-context', () => ({
  SafeAreaView: jest.requireActual('react-native').View,
  useSafeAreaInsets: () => ({ bottom: 0, left: 0, right: 0, top: 0 }),
}));
jest.mock('@tanstack/react-query', () => {
  const actual = jest.requireActual<typeof import('@tanstack/react-query')>('@tanstack/react-query');
  actual.notifyManager.setScheduler(queueMicrotask);
  return {
    ...actual,
    QueryClient: class extends actual.QueryClient {
      constructor(config?: import('@tanstack/react-query').QueryClientConfig) {
        super({
          ...config,
          defaultOptions: { ...config?.defaultOptions, queries: { ...config?.defaultOptions?.queries, gcTime: Infinity } },
        });
        mockClient = this;
      }
    },
  };
});
jest.mock('expo-router', () => ({
  Stack: Object.assign(() => {
    const React = jest.requireActual<typeof import('react')>('react');
    return React.createElement(mockSettingsScreen);
  }, { Screen: () => null }),
  useRouter: () => ({}),
}));
jest.mock('@/hooks/useTermsConsent', () => ({ useTermsConsentGate: jest.fn() }));
jest.mock('@/hooks/useChatMemory', () => ({
  useChatMemory: () => ({ refreshSettings: mockMemorySettings, busy: false }),
}));
jest.mock('@/lib/i18n', () => ({
  LANGUAGE_LABELS: { en: 'English' },
  LANGUAGES: ['en'],
  useI18n: () => ({ t: (key: string) => key }),
}));
jest.mock('@/lib/confirm', () => ({
  confirmAction: (_message: string, _label: string, _cancel: string, confirm: () => void) => {
    mockConfirm = confirm;
  },
  notify: jest.fn(),
}));
jest.mock('@/lib/auth', () => ({
  useAuth: () => ({ ready: true, user: mockOwner ? { id: mockOwner } : null }),
  getCurrentUserId: async () => mockOwner,
  signOut: jest.fn(async () => { mockOwner = null; }),
}));
jest.mock('@/lib/auth/client', () => ({
  isAuthConfigured: () => true,
  getSupabase: () => ({
    auth: {
      getSession: async () => ({
        data: { session: mockOwner ? { user: { id: mockOwner }, access_token: `token-${mockOwner}` } : null },
      }),
      getClaims: async (token: string) => ({
        data: { claims: { role: 'authenticated', sub: token.slice('token-'.length) } },
      }),
    },
  }),
}));

const request = jest.fn<Promise<Response>, [input: RequestInfo | URL, init?: RequestInit]>();
const originalFetch = globalThis.fetch;
const marker = (owner: string) => `${STORAGE_KEYS.accountDeletion}:${owner}`;
const roomId = '8b332bee-a5f9-4fc8-a945-2921f863bcd8';
const requestId = 'bbc311ef-de68-4a47-ad42-10ad376cd235';
const response = (status: number, code?: string): Response => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => code ? { code } : { user: { id: mockOwner } },
} as Response);
const pending = () => response(409, 'account_deletion_in_progress');

let deletionResponse: () => Promise<Response>;
let memberResponse: () => Response;
let view: ReactTestRenderer | undefined;

async function mount() {
  await act(async () => { view = create(<RootLayout />); });
}

async function switchOwner(owner: string | null) {
  mockOwner = owner;
  await act(async () => { view!.update(<RootLayout />); });
}

function displays(key: string) {
  return view!.root.findAll(node => node.children.includes(key)).length > 0;
}

function button(key: string) {
  return view!.root.findAll(node => node.type === Button && node.props.label === key)[0];
}

function deleteCalls() {
  return request.mock.calls.filter(([, options]) => options?.method === 'DELETE');
}

async function openConfirm() {
  await act(async () => {
    const row = view!.root.findAll(node => node.props.label === 'account.delete')[0];
    row.props.onPress();
  });
}

beforeEach(async () => {
  await AsyncStorage.clear();
  mockOwner = 'A';
  mockConfirm = undefined;
  jest.mocked(signOut).mockClear();
  globalThis.fetch = request;
  request.mockReset();
  memberResponse = () => response(200);
  deletionResponse = async () => pending();
  request.mockImplementation(async (_url, options) =>
    options?.method === 'DELETE' ? deletionResponse() : memberResponse());
  useChatConversationStore.getState().activate(null);
});

afterEach(async () => {
  if (view) await act(async () => { view!.unmount(); });
  mockClient?.clear();
  view = undefined;
  globalThis.fetch = originalFetch;
});

it('blocks member screens after acceptance and completes only after 204', async () => {
  await AsyncStorage.multiSet([
    [skinProfileKey('A'), 'account'],
    [pendingProfileKey('A'), 'draft'],
    [skinProfileKey('B'), 'other account'],
    [chatRoomDeletionKey('A', roomId), '1'],
    [chatRoomDeletionKey('B', roomId), '1'],
    [chatRequestRecoveryKey('A', roomId, requestId), '1'],
    [chatRequestRecoveryKey('B', roomId, requestId), '1'],
    [STORAGE_KEYS.cart, 'shared device data'],
  ]);
  await mount();
  mockClient.setQueryData(['skin-access', 'A'], { test: 'A' });
  mockClient.setQueryData(['skin-access', 'B'], { test: 'B' });
  useChatConversationStore.getState().activate('A');
  useChatConversationStore.getState().open({ type: 'general' });

  await openConfirm();
  await act(async () => {
    mockConfirm!();
    mockConfirm!();
  });
  expect(deleteCalls()).toHaveLength(1);
  expect(deleteCalls()[0][1]?.headers).toMatchObject({ Authorization: 'Bearer token-A' });
  expect(displays('account.deletePendingTitle')).toBe(true);
  expect(displays('my.deleteData')).toBe(false);
  expect(displays('account.deleteDone')).toBe(false);
  expect(signOut).not.toHaveBeenCalled();
  expect(await AsyncStorage.getItem(marker('A'))).toBe('1');
  expect(await AsyncStorage.getItem(skinProfileKey('A'))).toBeNull();
  expect(await AsyncStorage.getItem(pendingProfileKey('A'))).toBeNull();
  expect(await AsyncStorage.getItem(skinProfileKey('B'))).toBe('other account');
  expect(await AsyncStorage.getItem(chatRoomDeletionKey('A', roomId))).toBeNull();
  expect(await AsyncStorage.getItem(chatRoomDeletionKey('B', roomId))).toBe('1');
  expect(await AsyncStorage.getItem(chatRequestRecoveryKey('A', roomId, requestId))).toBeNull();
  expect(await AsyncStorage.getItem(chatRequestRecoveryKey('B', roomId, requestId))).toBe('1');
  expect(await AsyncStorage.getItem(STORAGE_KEYS.cart)).toBe('shared device data');
  expect(mockClient.getQueryData(['skin-access', 'A'])).toBeUndefined();
  expect(mockClient.getQueryData(['skin-access', 'B'])).toEqual({ test: 'B' });
  expect(useChatConversationStore.getState().conversations).toEqual({});

  deletionResponse = async () => response(503, 'account_deletion_unavailable');
  await act(async () => button('account.deleteCheck').props.onPress());
  expect(displays('account.deleteStatusUnavailable')).toBe(true);
  expect(await AsyncStorage.getItem(marker('A'))).toBe('1');

  deletionResponse = async () => response(204);
  await act(async () => button('account.deleteCheck').props.onPress());
  expect(signOut).toHaveBeenCalledTimes(1);
  expect(await AsyncStorage.getItem(marker('A'))).toBeNull();
  await switchOwner(null);
  expect(displays('account.deleteDone')).toBe(true);
  await act(async () => button('account.deleteClose').props.onPress());
  expect(displays('my.deleteData')).toBe(true);
}, 20000);

it('removes room-deletion and request recovery markers when device data is cleared', async () => {
  await AsyncStorage.multiSet([
    [chatRoomDeletionKey('A', roomId), '1'],
    [chatRoomDeletionKey('B', roomId), '1'],
    [chatRequestRecoveryKey('A', roomId, requestId), '1'],
    [chatRequestRecoveryKey('B', roomId, requestId), '1'],
  ]);
  await mount();
  const store = useChatConversationStore.getState();
  store.activate('A');
  store.restoreRoomDeletions(useChatConversationStore.getState().identity!.key, [roomId]);
  await act(async () => view!.root.findAll((node) => node.props.label === 'my.deleteData')[0].props.onPress());
  await act(async () => mockConfirm!());
  expect(await AsyncStorage.getItem(chatRoomDeletionKey('A', roomId))).toBeNull();
  expect(await AsyncStorage.getItem(chatRoomDeletionKey('B', roomId))).toBeNull();
  expect(await AsyncStorage.getItem(chatRequestRecoveryKey('A', roomId, requestId))).toBeNull();
  expect(await AsyncStorage.getItem(chatRequestRecoveryKey('B', roomId, requestId))).toBeNull();
  expect(useChatConversationStore.getState().conversations[roomId]).toBeUndefined();
  expect(deleteCalls()).toHaveLength(0);
});

it.each([503, 'network', 202] as const)('keeps the normal screen when initial receipt is unconfirmed (%s)', async outcome => {
  deletionResponse = async () => {
    if (outcome === 'network') throw new Error('response lost');
    return response(outcome);
  };
  await mount();
  await openConfirm();
  await act(async () => mockConfirm!());
  expect(displays('account.deleteUnavailable')).toBe(true);
  expect(displays('account.deletePendingTitle')).toBe(false);
  expect(displays('account.deleteDone')).toBe(false);
  expect(await AsyncStorage.getItem(marker('A'))).toBeNull();
  expect(signOut).not.toHaveBeenCalled();
});

it('retries local cleanup after an immediate 204 without sending another deletion', async () => {
  deletionResponse = async () => response(204);
  const cleanup = jest.mocked(AsyncStorage.multiRemove);
  const removeItems = cleanup.getMockImplementation()!;
  cleanup.mockRejectedValueOnce(new Error('disk error'));
  try {
    await mount();
    await openConfirm();
    await act(async () => mockConfirm!());
    expect(displays('account.deleteDone')).toBe(true);
    expect(displays('account.deleteCleanupFailed')).toBe(true);
    expect(signOut).not.toHaveBeenCalled();

    await act(async () => button('common.retry').props.onPress());
    expect(signOut).toHaveBeenCalledTimes(1);
    expect(displays('account.deleteCleanupFailed')).toBe(false);
    expect(deleteCalls()).toHaveLength(1);
  } finally {
    cleanup.mockReset().mockImplementation(removeItems);
  }
});

it('restores a receipt on app launch and distinguishes session expiry from completion', async () => {
  await AsyncStorage.setItem(marker('A'), '1');
  await mount();
  expect(displays('account.deletePendingTitle')).toBe(true);
  expect(request).not.toHaveBeenCalled();
  deletionResponse = async () => response(401);
  await act(async () => button('account.deleteCheck').props.onPress());
  expect(displays('account.deleteSessionEnded')).toBe(true);
  expect(button('account.deleteCheck')).toBeUndefined();
  expect(displays('account.deleteDone')).toBe(false);
  await switchOwner(null);
  expect(displays('account.deleteSessionEnded')).toBe(true);
  await act(async () => button('account.deleteClose').props.onPress());
  await switchOwner('B');
  expect(displays('my.deleteData')).toBe(true);
  expect(await AsyncStorage.getItem(marker('A'))).toBe('1');
});

it('checks the signed receipt and shows completion after the auth session ends', async () => {
  const receipt = 'a'.repeat(32) + '.' + 'b'.repeat(64);
  const accepted = { ...pending(), json: async () => ({
    code: 'account_deletion_in_progress', deletionReceipt: receipt,
  }) } as Response;
  request.mockImplementation(async (url, options) => {
    if (options?.method === 'DELETE') return accepted;
    if (options?.method === 'POST') {
      expect(String(url)).toContain('/api/me/deletion-status');
      expect(options.headers).not.toHaveProperty('Authorization');
      expect(JSON.parse(String(options.body))).toEqual({ receipt });
      return { ...response(200), json: async () => ({ status: 'complete' }) } as Response;
    }
    return memberResponse();
  });
  await mount();
  await openConfirm();
  await act(async () => mockConfirm!());
  expect(await AsyncStorage.getItem(marker('A'))).toBe(receipt);
  await switchOwner(null);
  expect(displays('account.deletePendingTitle')).toBe(true);
  expect(displays('account.deleteDone')).toBe(false);
  const remove = jest.mocked(AsyncStorage.removeItem);
  const removeItem = remove.getMockImplementation()!;
  await act(async () => {
    await new Promise<void>(resolve => {
      remove.mockImplementationOnce(async (...args) => {
        await removeItem(...args);
        resolve();
      });
    });
  });
  expect(displays('account.deleteDone')).toBe(true);
  expect(displays('account.deleteCleanupFailed')).toBe(false);
  expect(deleteCalls()).toHaveLength(1);
  expect(await AsyncStorage.getItem(marker('A'))).toBeNull();
}, 15000);

it('recovers an accepted request from member status without resubmitting', async () => {
  memberResponse = () => response(403, 'account_unavailable');
  await mount();
  expect(displays('account.deletePendingTitle')).toBe(true);
  expect(await AsyncStorage.getItem(marker('A'))).toBe('1');
  expect(deleteCalls()).toHaveLength(0);
  await act(async () => button('account.deleteLeave').props.onPress());
  await switchOwner(null);
  expect(signOut).toHaveBeenCalledTimes(1);
  expect(displays('my.deleteData')).toBe(true);
  expect(await AsyncStorage.getItem(marker('A'))).toBe('1');
});

it.each([204, 409])('keeps a late %s from changing the new account', async status => {
  let finish!: (result: Response) => void;
  deletionResponse = () => new Promise(resolve => { finish = resolve; });
  await mount();
  await openConfirm();
  await act(async () => mockConfirm!());
  await switchOwner('B');
  mockClient.setQueryData(['me', 'B'], { user: { id: 'B' } });
  await act(async () => finish(status === 204 ? response(204) : pending()));
  expect(signOut).not.toHaveBeenCalled();
  expect(displays('my.deleteData')).toBe(true);
  expect(displays('account.deleteDone')).toBe(false);
  expect(displays('account.deletePendingTitle')).toBe(false);
  expect(mockClient.getQueryData(['me', 'B'])).toEqual({ user: { id: 'B' } });
  expect(await AsyncStorage.getItem(marker('B'))).toBeNull();
  expect(await AsyncStorage.getItem(marker('A'))).toBe(status === 409 ? '1' : null);
});

it('does not send a stale confirmation using the next account', async () => {
  await mount();
  await openConfirm();
  await switchOwner('B');
  await act(async () => mockConfirm!());
  await expect(apiDelete('/api/me', { expectedUserId: 'A', expectedStatus: 204 }))
    .rejects.toMatchObject<Partial<ApiError>>({ code: 'owner_changed' });
  expect(deleteCalls()).toHaveLength(0);
});
