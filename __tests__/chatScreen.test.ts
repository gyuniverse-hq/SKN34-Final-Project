import AsyncStorage from '@react-native-async-storage/async-storage';
import { createElement } from 'react';
import { AppState, Keyboard, KeyboardAvoidingView, Platform, Text, TextInput, type AppStateStatus } from 'react-native';
import { act, create, type ReactTestInstance, type ReactTestRenderer } from 'react-test-renderer';
import ChatScreen from '@/app/chat';
import type { BeautyChatContext, ChatStyleRecipe } from '@/types';
import { ChatProducts, CompoundProductCards } from '@/components/chat/ChatProducts';
import { IngredientResult } from '@/components/chat/IngredientResult';
import { RecentConversations } from '@/components/chat/RecentConversations';
import { StyleRecipeResult } from '@/components/chat/StyleRecipeResult';
import { ApiError } from '@/lib/api';
import * as chatApi from '@/lib/api';
import * as confirmations from '@/lib/confirm';
import { en } from '@/lib/i18n/en';
import { ko } from '@/lib/i18n/ko';
import { ja } from '@/lib/i18n/ja';
import { zh } from '@/lib/i18n/zh';
import { chatRequestRecoveryKey, chatRoomDeletionKey } from '@/lib/storage';
import { useChatConversationStore } from '@/store/chatConversationStore';

jest.setTimeout(20000);

const mockMutateAsync = jest.fn();
const mockMemoryRefresh = jest.fn();
const mockMemoryProposalRefresh = jest.fn();
const mockMemorySettingsRefresh = jest.fn();
const mockMemoryConfirm = jest.fn();
const mockMemoryUpdate = jest.fn();
const mockMemoryRemove = jest.fn();
const mockUseChat = jest.fn(() => ({ mutateAsync: mockMutateAsync, isPending: false }));
const mockProductsByIds = jest.fn();
const mockPush = jest.fn();
const mockRefetch = jest.fn();
const mockAuth = jest.fn((): { user: { id: string } | null; ready: boolean } => ({ user: null, ready: true }));
let mockAuthListener: ((event: string, session: { user: { id: string } } | null) => void) | undefined;
let mockSupabaseEnabled = false;
let mockScreenFocused = false;
let mockLanguage = 'ko';
let mockDictionary: Record<string, string> | undefined;

const beautyContext: BeautyChatContext = {
  version: 1, issuedAt: 1000, candidateIds: ['p1', 'p2'], scopeIds: ['p1', 'p2'],
  selectedProductId: null,
  filters: { category: 'lip', maxPriceKRW: 20000, fragranceFree: false, moisturizing: true, query: '' },
};

jest.mock('@/hooks/useChat', () => ({ useChat: () => mockUseChat() }));
jest.mock('@/hooks/useChatMemory', () => ({
  useChatMemory: () => ({
    memories: [], busy: false,
    refresh: mockMemoryRefresh, refreshProposals: mockMemoryProposalRefresh,
    refreshSettings: mockMemorySettingsRefresh,
    confirm: mockMemoryConfirm, update: mockMemoryUpdate, remove: mockMemoryRemove,
  }),
}));
jest.mock('@/lib/auth', () => ({ useAuth: () => mockAuth(), getAccessToken: async () => null }));
jest.mock('@/lib/auth/client', () => ({
  getSupabase: () => mockSupabaseEnabled ? { auth: { onAuthStateChange: (listener: typeof mockAuthListener) => {
    mockAuthListener = listener;
    return { data: { subscription: { unsubscribe: jest.fn() } } };
  } } } : null,
  isAuthConfigured: () => false,
}));
jest.mock('@/lib/i18n', () => ({ useI18n: () => ({ t: (key: string) => mockDictionary?.[key] ?? key, language: mockLanguage }) }));
jest.mock('@/lib/queries', () => ({
  useProductsByIds: (ids: string[]) => mockProductsByIds(ids),
  useStyleLooks: () => ({ data: [{ id: '_video-1', title: 'Test look', products: [{ zone: 'lip' }] }, { id: '_video-2', title: 'Other look', products: [] }] }),
  useLook: () => ({}),
  useProduct: (id: string) => ({ data: { id, name: id, shades: [{ id: `${id}-01`, name: '01' }, { id: `${id}-02`, name: '02' }] } }),
}));
jest.mock('@/components/chat/ChatProducts', () => ({ ChatProducts: () => null, CompoundProductCards: () => null }));
jest.mock('@expo/vector-icons/Ionicons', () => () => null);
const mockRouteParams: { recipeKind?: string; recipeLookId?: string; productId?: string; shadeId?: string } = {};
jest.mock('expo-router', () => ({
  Stack: { Screen: ({ options }: { options: { headerRight?: () => unknown } }) => options.headerRight?.() ?? null },
  useRouter: () => ({ push: mockPush }),
  useLocalSearchParams: () => mockRouteParams,
  useIsFocused: () => mockScreenFocused,
}));
jest.mock('expo-router/react-navigation', () => ({ useHeaderHeight: () => 88 }));
jest.mock('react-native-safe-area-context', () => ({
  SafeAreaView: ({ children }: { children: unknown }) => children,
}));

function buttonWithText(root: ReactTestInstance, text: string) {
  const label = root.findAll((item) => item.props.children === text)[0];
  let button = label?.parent;
  while (button && typeof button.props.onPress !== 'function') button = button.parent;
  if (!button) throw new Error(`Button not found: ${text}`);
  return button;
}

async function renderScreen(): Promise<ReactTestRenderer> {
  let renderer!: ReactTestRenderer;
  await act(async () => {
    renderer = create(createElement(ChatScreen), {
      createNodeMock: () => ({ focus: jest.fn(), scrollToEnd: jest.fn() }),
    });
  });
  return renderer;
}

beforeEach(async () => {
  await AsyncStorage.clear();
  jest.spyOn(chatApi, 'apiChatUserRequest').mockRejectedValue(new ApiError('disabled', 503, 'persistence_disabled'));
  useChatConversationStore.setState({ identity: undefined, conversations: {}, latest: {} });
  delete mockRouteParams.recipeKind; delete mockRouteParams.recipeLookId;
  delete mockRouteParams.productId; delete mockRouteParams.shadeId;
  mockMutateAsync.mockReset();
  mockMemoryRefresh.mockReset().mockRejectedValue(new ApiError('Memory unavailable', 503, 'memory_unavailable'));
  mockMemoryProposalRefresh.mockReset().mockResolvedValue(undefined);
  mockMemorySettingsRefresh.mockReset().mockResolvedValue(undefined);
  mockMemoryConfirm.mockReset();
  mockMemoryUpdate.mockReset();
  mockMemoryRemove.mockReset();
  mockUseChat.mockReturnValue({ mutateAsync: mockMutateAsync, isPending: false });
  mockProductsByIds.mockReset().mockReturnValue({ data: [], isPending: false, isError: false, refetch: mockRefetch });
  mockPush.mockReset();
  mockRefetch.mockReset();
  mockAuth.mockReturnValue({ user: null, ready: true });
  mockAuthListener = undefined;
  mockSupabaseEnabled = false;
  mockScreenFocused = false;
  mockLanguage = 'ko';
  mockDictionary = undefined;
});

it('shows the server memory candidate and saves it only after confirmation', async () => {
  mockAuth.mockReturnValue({ user: { id: 'A' }, ready: true });
  mockMemoryRefresh.mockResolvedValue([]);
  mockMemoryConfirm.mockResolvedValue({ memoryId: 'memory-1', memoryVersion: 1 });
  const server = jest.spyOn(chatApi, 'apiChatUserRequest').mockResolvedValue({
    conversationId: 'server-room', conversationVersion: 0,
  });
  const proposal = { proposalId: 'proposal-1', version: 1, kind: 'preference',
    value: '코랄 립 기억해줘', consentScope: 'future_consultations', expiresAt: '2099-01-01T00:00:00Z' };
  mockMutateAsync.mockResolvedValue({ answer: '확인해 주세요', products: [], memoryProposal: proposal,
    conversation: { id: 'server-room', version: 1, turnId: 'turn', persistenceStatus: 'stored' } });
  const view = await renderScreen();
  await act(async () => view.root.findByType(TextInput).props.onChangeText('코랄 립 기억해줘'));
  await act(async () => view.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress());
  expect(view.root.findAll((item) => item.props.children === '코랄 립 기억해줘').length).toBeGreaterThan(0);
  expect(mockMemoryConfirm).not.toHaveBeenCalled();
  await act(async () => buttonWithText(view.root, 'chat.memory.confirm').props.onPress());
  expect(mockMemoryConfirm).toHaveBeenCalledWith(proposal);
  expect(view.root.findAllByType(Text).filter((item) => item.props.children === 'chat.memory.saved')).toHaveLength(1);
  server.mockRestore();
  await act(async () => view.unmount());
});

it.each(['message', 'selection'])('reloads the current room on a %s version conflict', async (conflict) => {
  mockAuth.mockReturnValue({ user: { id: 'A' }, ready: true });
  const subject = conflict === 'selection' ? { type: 'product', productId: 'p1' } : { type: 'general' };
  if (conflict === 'selection') Object.assign(mockRouteParams, { productId: 'p1', shadeId: 'p1-01' });
  const changed = new ApiError('Conversation version changed', 409, 'conversation_conflict');
  let version = 0;
  const server = jest.spyOn(chatApi, 'apiChatUserRequest').mockImplementation(async (path, method) => {
    if (path === '/api/chat/conversations' && method === 'POST') {
      return { conversationId: 'server-room', conversationVersion: 0 };
    }
    if (path === '/api/chat/conversations/server-room/state' && method === 'PATCH') {
      if (version === 0) throw changed;
      return { conversationVersion: ++version };
    }
    if (path === '/api/chat/conversations/server-room' && method === 'GET') {
      version = 4;
      return {
        conversationId: 'server-room', conversationVersion: version, subject,
        context: conflict === 'selection' ? { product: { selectedProductId: 'p1', selectedShadeId: 'p1-01' } } : {},
        messages: [{ id: 'other-turn', role: 'assistant', text: '다른 기기의 답변', displayPayload: {} }],
      };
    }
    throw new Error('unexpected request');
  });
  if (conflict === 'message') mockMutateAsync.mockRejectedValueOnce(changed);
  mockMutateAsync.mockImplementation(async () => ({
    answer: '새 답변', products: [],
    conversation: { id: 'server-room', version: version + 1, turnId: 'turn', persistenceStatus: 'stored' },
  }));
  const view = await renderScreen();
  await act(async () => view.root.findByType(TextInput).props.onChangeText('상담을 이어서 할게'));
  await act(async () => view.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress());
  expect(server).toHaveBeenCalledWith('/api/chat/conversations/server-room', 'GET', 'A');
  expect(view.root.findAllByType(Text).some((item) => item.props.children === '다른 기기의 답변')).toBe(true);
  expect(view.root.findByType(TextInput).props.value).toBe('상담을 이어서 할게');
  expect(mockMutateAsync).toHaveBeenCalledTimes(conflict === 'selection' ? 0 : 1);
  await act(async () => view.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress());
  expect(mockMutateAsync).toHaveBeenLastCalledWith(expect.objectContaining({
    conversationId: 'server-room', expectedConversationVersion: version,
  }));
  server.mockRestore();
  await act(async () => view.unmount());
});

it('recovers a committed chat after response loss without repeating its selection patch or chat', async () => {
  mockAuth.mockReturnValue({ user: { id: 'A' }, ready: true });
  mockMemoryRefresh.mockResolvedValue([]);
  Object.assign(mockRouteParams, { productId: 'p1', shadeId: 'p1-01' });
  const server = jest.spyOn(chatApi, 'apiChatUserRequest').mockImplementation(async (path, method) => {
    if (path === '/api/chat/conversations' && method === 'POST') {
      return { conversationId: 'server-room', conversationVersion: 0 };
    }
    if (path === '/api/chat/conversations/server-room/state' && method === 'PATCH') {
      return { conversationVersion: 1 };
    }
    if (path.startsWith('/api/chat/conversations/server-room/requests/') && method === 'GET') return {
      requestId: path.split('/').at(-1), status: 'COMMITTED',
      response: { conversation: { id: 'server-room', version: 2, persistenceStatus: 'stored' } },
    };
    if (path === '/api/chat/conversations/server-room' && method === 'GET') return {
      conversationId: 'server-room', conversationVersion: 2, subject: { type: 'product', productId: 'p1' },
      context: { product: { selectedProductId: 'p1', selectedShadeId: 'p1-01' } }, nextMessageCursor: null,
      messages: [{ id: 'server-user', role: 'user', text: '이 제품 알려줘' },
        { id: 'server-answer', role: 'assistant', text: 'Restored answer' }],
    };
    throw new Error('unexpected request');
  });
  let markerAtSend: string | null = null;
  mockMutateAsync.mockImplementationOnce(async ({ requestId }) => {
    markerAtSend = await AsyncStorage.getItem(chatRequestRecoveryKey('A', 'server-room', requestId));
    throw new ApiError('offline', 0, 'network');
  });
  const view = await renderScreen();
  await act(async () => view.root.findByType(TextInput).props.onChangeText('이 제품 알려줘'));
  await act(async () => view.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress());
  const patches = server.mock.calls.filter((call) => call[1] === 'PATCH');
  expect(patches).toHaveLength(1);
  expect(patches[0][3]).toMatchObject({ expectedConversationVersion: 0,
    operation: 'select_shade', payload: { productId: 'p1', shadeId: 'p1-01' } });
  expect(mockMutateAsync).toHaveBeenLastCalledWith(expect.objectContaining({
    conversationId: 'server-room', expectedConversationVersion: 1,
  }));
  expect(mockMutateAsync).toHaveBeenCalledTimes(1);
  expect(markerAtSend).toBe('1');
  expect(await AsyncStorage.getAllKeys()).toEqual([]);
  expect(view.root.findAllByType(Text).some((item) => item.props.children === 'Restored answer')).toBe(true);
  server.mockRestore();
  await act(async () => view.unmount());
});

it('loads and resumes a server conversation without reviving an old candidate session', async () => {
  mockAuth.mockReturnValue({ user: { id: 'A' }, ready: true });
  const server = jest.spyOn(chatApi, 'apiChatUserRequest').mockImplementation(async (path, method) => {
    if (path === '/api/chat/conversations' && method === 'GET') return { conversations: [{
      conversationId: 'saved-room', conversationVersion: 4, subject: { type: 'general' },
      updatedAt: '2026-01-01T00:00:00Z',
    }], nextCursor: null };
    if (path === '/api/chat/conversations/saved-room' && method === 'GET') return {
      conversationId: 'saved-room', conversationVersion: 4, subject: { type: 'general' },
      context: { product: { selectedProductId: 'p1', selectedShadeId: 'p1-01' } },
      messages: [{ id: 'saved-question', role: 'user', text: 'previous question' },
        { id: 'saved-answer', role: 'assistant', text: 'previous answer', displayPayload: { products: [] } }],
      nextMessageCursor: null,
    };
    throw new Error('unexpected request');
  });
  const view = await renderScreen();
  await act(async () => view.root.findByProps({ accessibilityLabel: 'chat.room.recent' }).props.onPress());
  const recent = view.root.findByType(RecentConversations);
  await act(async () => recent.props.onSelect('saved-room'));
  expect(view.root.findAllByType(Text).some((item) => item.props.children === 'previous answer')).toBe(true);
  const room = useChatConversationStore.getState().conversations['saved-room'];
  expect(room.view.linkedProduct).toMatchObject({ productId: 'p1', shadeId: 'p1-01' });
  expect(room.conversation.beautyContext?.session).toBeUndefined();
  expect(mockMutateAsync).not.toHaveBeenCalled();
  server.mockRestore();
  await act(async () => view.unmount());
});

it('loads a saved transcript after a cold restart and sends a follow-up to the same room', async () => {
  mockAuth.mockReturnValue({ user: { id: 'A' }, ready: true });
  const summary = { conversationId: 'saved-room', conversationVersion: 1, subject: { type: 'general' },
    updatedAt: '2026-01-01T00:00:00Z' };
  const server = jest.spyOn(chatApi, 'apiChatUserRequest').mockClear().mockImplementation(async (path, method) => {
    if (path === '/api/chat/conversations' && method === 'POST') return { ...summary, conversationVersion: 0 };
    if (path === '/api/chat/conversations' && method === 'GET') return { conversations: [summary], nextCursor: null };
    if (path === '/api/chat/conversations/saved-room' && method === 'GET') return {
      ...summary, context: {}, nextMessageCursor: null, messages: [
        { id: 'question', role: 'user', text: 'First question' },
        { id: 'answer', role: 'assistant', text: 'Saved answer' },
      ],
    };
    throw new Error('Unexpected chat request');
  });
  mockMutateAsync.mockResolvedValueOnce({ answer: 'Saved answer', products: [],
    conversation: { id: 'saved-room', version: 1, turnId: 'first', persistenceStatus: 'stored' } })
    .mockResolvedValueOnce({ answer: 'Follow-up answer', products: [],
      conversation: { id: 'saved-room', version: 2, turnId: 'next', persistenceStatus: 'stored' } });
  const first = await renderScreen();
  await act(async () => first.root.findByType(TextInput).props.onChangeText('First question'));
  await act(async () => first.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress());
  await act(async () => first.unmount());
  useChatConversationStore.setState({ identity: undefined, conversations: {}, latest: {} });

  const initialState = AppState.currentState;
  AppState.currentState = 'active';
  mockScreenFocused = true;
  const view = await renderScreen();
  expect(server.mock.calls.slice(1)).toEqual([['/api/chat/conversations', 'GET', 'A']]);
  expect(mockMutateAsync).toHaveBeenCalledTimes(1);
  await act(async () => view.root.findByProps({ accessibilityLabel: 'chat.room.recent' }).props.onPress());
  const callCount = server.mock.calls.length;
  await act(async () => view.root.findByProps({ accessibilityLabel: 'chat.room.refresh' }).props.onPress());
  expect(server.mock.calls.slice(callCount)).toEqual([['/api/chat/conversations', 'GET', 'A']]);
  await act(async () => view.root.findByType(RecentConversations).props.onSelect('saved-room'));
  expect(view.root.findAllByType(Text).some((item) => item.props.children === 'Saved answer')).toBe(true);
  await act(async () => view.root.findByType(TextInput).props.onChangeText('Follow-up question'));
  await act(async () => view.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress());
  expect(mockMutateAsync).toHaveBeenLastCalledWith(expect.objectContaining({
    message: 'Follow-up question', conversationId: 'saved-room', expectedConversationVersion: 1,
  }));
  expect(server.mock.calls.filter(([, method]) => method === 'POST')).toHaveLength(1);
  await act(async () => view.unmount());
  AppState.currentState = initialState;
  server.mockRestore();
});

it('checks a saved pending request after restart and requires explicit dismissal if it is not found', async () => {
  const requestId = '970c8147-015d-46f3-873b-e9c764b4cdd4';
  const marker = chatRequestRecoveryKey('A', 'saved-room', requestId);
  await AsyncStorage.setItem(marker, '1');
  mockAuth.mockReturnValue({ user: { id: 'A' }, ready: true });
  const summary = { conversationId: 'saved-room', conversationVersion: 1, subject: { type: 'general' },
    updatedAt: '2026-01-01T00:00:00Z' };
  const statusPath = `/api/chat/conversations/saved-room/requests/${requestId}`;
  let pending = true;
  const server = jest.spyOn(chatApi, 'apiChatUserRequest').mockClear().mockImplementation(async (path, method) => {
    if (method !== 'GET') throw new Error('Unexpected chat write');
    if (path === '/api/chat/conversations') return { conversations: [summary], nextCursor: null };
    if (path === '/api/chat/conversations/saved-room') return { ...summary, context: {}, messages: [] };
    if (path === statusPath) {
      if (pending) return { requestId, status: 'IN_PROGRESS' };
      throw new ApiError('Request not found', 404, 'not_found');
    }
    throw new Error('Unexpected chat request');
  });
  const view = await renderScreen();
  await act(async () => view.root.findByProps({ accessibilityLabel: 'chat.room.recent' }).props.onPress());
  await act(async () => view.root.findByType(RecentConversations).props.onSelect('saved-room'));
  expect(view.root.findAllByType(Text).map(({ props }) => props.children)).toContain('chat.recovery.in_progress');
  expect(view.root.findByType(TextInput).props.editable).toBe(false);
  pending = false;
  await act(async () => buttonWithText(view.root, 'chat.recovery.check').props.onPress());
  expect(server.mock.lastCall).toEqual([statusPath, 'GET', 'A']);
  expect(view.root.findAllByType(Text).map(({ props }) => props.children)).toContain('chat.recovery.not_found');
  expect(await AsyncStorage.getItem(marker)).toBe('1');
  expect(mockMutateAsync).not.toHaveBeenCalled();
  await act(async () => buttonWithText(view.root, 'chat.recovery.dismiss').props.onPress());
  expect(await AsyncStorage.getItem(marker)).toBeNull();
  expect(view.root.findByType(TextInput).props.editable).toBe(true);
  await act(async () => view.unmount());
  server.mockRestore();
});

it('preserves the live draft after interruption and uses a new ID only after the user sends it', async () => {
  mockAuth.mockReturnValue({ user: { id: 'A' }, ready: true });
  let status: 'IN_PROGRESS' | 'INTERRUPTED' = 'IN_PROGRESS';
  const server = jest.spyOn(chatApi, 'apiChatUserRequest').mockImplementation(async (path, method) => {
    if (path === '/api/chat/conversations' && method === 'POST') return { conversationId: 'saved-room', conversationVersion: 0 };
    if (path.startsWith('/api/chat/conversations/saved-room/requests/') && method === 'GET') {
      return { requestId: path.split('/').at(-1), status };
    }
    throw new Error('Unexpected chat request');
  });
  mockMutateAsync.mockRejectedValueOnce(new ApiError('Response lost', 0, 'network'))
    .mockResolvedValueOnce({ answer: 'New answer', products: [],
      conversation: { id: 'saved-room', version: 1, turnId: 'new', persistenceStatus: 'stored' } });
  const view = await renderScreen();
  const send = () => view.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress();
  await act(async () => view.root.findByType(TextInput).props.onChangeText('My question'));
  await act(async () => send());
  const firstRequestId = mockMutateAsync.mock.calls[0][0].requestId;
  status = 'INTERRUPTED';
  await act(async () => buttonWithText(view.root, 'chat.recovery.check').props.onPress());
  expect(await AsyncStorage.getItem(chatRequestRecoveryKey('A', 'saved-room', firstRequestId))).toBeNull();
  expect(view.root.findByType(TextInput).props.value).toBe('My question');
  expect(view.root.findByType(TextInput).props.editable).toBe(true);
  expect(mockMutateAsync).toHaveBeenCalledTimes(1);
  await act(async () => send());
  expect(mockMutateAsync).toHaveBeenCalledTimes(2);
  expect(mockMutateAsync.mock.lastCall![0].requestId).not.toBe(firstRequestId);
  expect(view.root.findAllByType(Text).map(({ props }) => props.children)).toContain('New answer');
  await act(async () => view.unmount());
  server.mockRestore();
});

it('rechecks the active room on focus and foreground return, closing it only on confirmed deletion', async () => {
  mockAuth.mockReturnValue({ user: { id: 'A' }, ready: true });
  const summary = { conversationId: 'saved-room', conversationVersion: 1, subject: { type: 'general' },
    updatedAt: '2026-01-01T00:00:00Z' };
  let result: 'found' | 'unavailable' | 'deleted' = 'found';
  const server = jest.spyOn(chatApi, 'apiChatUserRequest').mockClear().mockImplementation(async (path, method) => {
    if (method === 'GET' && path === '/api/chat/conversations') {
      return { conversations: result === 'found' ? [summary] : [], nextCursor: null };
    }
    if (method !== 'GET' || path !== '/api/chat/conversations/saved-room') throw new Error('Unexpected chat request');
    if (result === 'unavailable') throw new ApiError('Network unavailable', 0, 'network');
    if (result === 'deleted') throw new ApiError('Conversation not found', 404, 'not_found');
    return { ...summary, context: {}, nextMessageCursor: null, messages: [{ id: 'm', role: 'user', text: 'Previous question' }] };
  });
  const initialState = AppState.currentState;
  AppState.currentState = 'active';
  let onAppState!: (state: AppStateStatus) => void;
  const removeListener = jest.fn();
  const listen = jest.spyOn(AppState, 'addEventListener').mockImplementation((_type, listener) => {
    onAppState = listener;
    return { remove: removeListener };
  });
  const view = await renderScreen();
  await act(async () => view.root.findByProps({ accessibilityLabel: 'chat.room.recent' }).props.onPress());
  await act(async () => view.root.findByType(RecentConversations).props.onSelect('saved-room'));
  result = 'unavailable';
  mockScreenFocused = true;
  await act(async () => view.update(createElement(ChatScreen)));
  expect(server.mock.calls.slice(-2)).toEqual([
    ['/api/chat/conversations', 'GET', 'A'], ['/api/chat/conversations/saved-room', 'GET', 'A'],
  ]);
  expect(useChatConversationStore.getState().conversations['saved-room']).toBeDefined();
  result = 'deleted';
  await act(async () => { onAppState('background'); onAppState('active'); });
  expect(useChatConversationStore.getState().conversations['saved-room']).toBeUndefined();
  expect(view.root.findByType(TextInput).props.value).toBe('');
  expect(mockMutateAsync).not.toHaveBeenCalled();
  await act(async () => view.unmount());
  expect(removeListener).toHaveBeenCalledTimes(1);
  AppState.currentState = initialState;
  listen.mockRestore();
  server.mockRestore();
});

it('renders safe recent-room titles and previews before and after opening details', async () => {
  mockAuth.mockReturnValue({ user: { id: 'A' }, ready: true });
  const first = { conversationId: 'product-question', conversationVersion: 2, subject: { type: 'general' },
    updatedAt: '2026-01-01T00:00:02Z', listSummary: { titleTopic: 'product', previewTopics: ['hydration', 'price'] } };
  const other = { ...first, conversationId: 'ingredient-question', updatedAt: '2026-01-01T00:00:01Z',
    listSummary: { titleTopic: 'ingredient', previewTopics: [] } };
  const privateText = 'My email is synthetic@example.invalid. Please suggest a moisturizing lip product.';
  const server = jest.spyOn(chatApi, 'apiChatUserRequest').mockImplementation(async (path, method) => {
    if (path === '/api/chat/conversations' && method === 'GET') return { conversations: [first, other], nextCursor: null };
    if (path === '/api/chat/conversations/product-question' && method === 'GET') return {
      ...first, context: {}, messages: [{ id: 'original', role: 'user', text: privateText }],
    };
    throw new Error('Unexpected recent chat request');
  });
  const view = await renderScreen();
  const openRecent = () => view.root.findByProps({ accessibilityLabel: 'chat.room.recent' }).props.onPress();
  const recent = () => view.root.findByType(RecentConversations);
  const textLabels = () => recent().findAllByType(Text).map((item) => item.props.children);
  await act(async () => openRecent());
  expect(textLabels()).toEqual(expect.arrayContaining(['chat.room.product', 'careTag.hydrating · chat.option.price', 'chat.ui.ingredient']));
  await act(async () => recent().props.onSelect('product-question'));
  expect(view.root.findAllByType(Text).some((item) => item.props.children === privateText)).toBe(true);
  await act(async () => openRecent());
  expect(textLabels()).not.toContain(privateText);
  expect(recent().findAllByProps({ accessibilityHint: privateText })).toHaveLength(0);
  expect(textLabels()).toContain('careTag.hydrating · chat.option.price');
  await act(async () => view.unmount());
  server.mockRestore();
});

it('confirms deletion, blocks the active room after failure and opens a blank chat after retry', async () => {
  mockAuth.mockReturnValue({ user: { id: 'A' }, ready: true });
  const deleteRoom = jest.fn().mockRejectedValueOnce(new ApiError('Response lost', 0, 'network'))
    .mockResolvedValueOnce(undefined);
  const summary = (conversationId: string) => ({
    conversationId, conversationVersion: 2, subject: { type: 'general' }, updatedAt: '2026-01-01T00:00:00Z',
  });
  const server = jest.spyOn(chatApi, 'apiChatUserRequest').mockImplementation(async (path, method) => {
    if (path === '/api/chat/conversations' && method === 'GET') {
      return { conversations: [{ ...summary('saved-room'), listSummary: { titleTopic: 'product', previewTopics: ['price'] } },
        summary('other-room')], nextCursor: null };
    }
    if (path === '/api/chat/conversations/saved-room' && method === 'GET') {
      return { ...summary('saved-room'), context: {}, nextMessageCursor: null,
        messages: [{ id: 'previous-question', role: 'user', text: 'Question to delete' }] };
    }
    if (method === 'DELETE') return deleteRoom(path);
    throw new Error('Unexpected chat request');
  });
  const confirm = jest.spyOn(confirmations, 'confirmAction').mockImplementation(() => {});
  const view = await renderScreen();
  await act(async () => view.root.findByProps({ accessibilityLabel: 'chat.room.recent' }).props.onPress());
  await act(async () => view.root.findByType(RecentConversations).props.onSelect('saved-room'));
  await act(async () => view.root.findByProps({ accessibilityLabel: 'chat.room.recent' }).props.onPress());
  const pressDelete = () => view.root.findAllByProps({ accessibilityHint: 'chat.option.price' })[0].props.onPress();
  await act(async () => pressDelete());
  expect(confirm).toHaveBeenCalledWith('chat.room.deleteConfirm', 'common.delete', 'common.cancel', expect.any(Function));
  expect(deleteRoom).not.toHaveBeenCalled();
  expect(useChatConversationStore.getState().conversations['saved-room']).toBeDefined();
  await act(async () => pressDelete());
  await act(async () => { confirm.mock.lastCall![3](); });
  expect(view.root.findAllByType(TextInput)).toHaveLength(0);
  expect(view.root.findAllByType(Text).some((item) => item.props.children === 'Question to delete')).toBe(false);
  await act(async () => view.root.findByType(RecentConversations).props.onClose());
  await act(async () => buttonWithText(view.root, 'common.retry').props.onPress());
  expect(deleteRoom.mock.calls).toEqual([
    ['/api/chat/conversations/saved-room'], ['/api/chat/conversations/saved-room'],
  ]);
  const store = useChatConversationStore.getState();
  expect(store.conversations['saved-room']).toBeUndefined();
  expect(store.conversations['other-room']).toBeDefined();
  expect(store.conversations[store.latest.general].conversation.serverId).toBeUndefined();
  expect(view.root.findByType(TextInput).props.value).toBe('');
  expect(mockMutateAsync).not.toHaveBeenCalled();
  await act(async () => view.unmount());
  confirm.mockRestore();
  server.mockRestore();
});

it('deletes a guest chat locally and ignores an answer that arrives after deletion', async () => {
  const server = jest.spyOn(chatApi, 'apiChatUserRequest').mockClear();
  const confirm = jest.spyOn(confirmations, 'confirmAction').mockImplementation(() => {});
  let answer!: (value: unknown) => void;
  mockMutateAsync.mockImplementationOnce(() => new Promise((resolve) => { answer = resolve; }));
  const view = await renderScreen();
  const id = Object.keys(useChatConversationStore.getState().conversations)[0];
  await act(async () => view.root.findByType(TextInput).props.onChangeText('Guest question'));
  await act(async () => view.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress());
  await act(async () => view.root.findByProps({ accessibilityLabel: 'chat.room.recent' }).props.onPress());
  await act(async () => view.root.findAllByProps({ accessibilityHint: 'Guest question' })[0].props.onPress());
  await act(async () => { confirm.mock.lastCall![3](); });
  await act(async () => { answer({ answer: 'Late response', products: [] }); });
  const store = useChatConversationStore.getState();
  expect(store.conversations[id]).toBeUndefined();
  expect(Object.values(store.conversations).map((record) => record.messages)).toEqual([[]]);
  expect(view.root.findByType(TextInput).props.value).toBe('');
  expect(server).not.toHaveBeenCalled();
  await act(async () => view.unmount());
  confirm.mockRestore();
  server.mockRestore();
});

it('shows a restored deletion retry without room details or an automatic DELETE', async () => {
  const id = 'bdf6defe-cd5c-4a4f-91d7-7222f6313792';
  const marker = chatRoomDeletionKey('A', id);
  await AsyncStorage.setItem(marker, '1');
  mockAuth.mockReturnValue({ user: { id: 'A' }, ready: true });
  const server = jest.spyOn(chatApi, 'apiChatUserRequest').mockClear().mockImplementation(async (path, method) => {
    if (path === '/api/chat/conversations' && method === 'GET') return { conversations: [{
      conversationId: id, conversationVersion: 4, subject: { type: 'product', productId: 'hidden-product' },
      updatedAt: '2026-01-01T00:00:00Z',
    }], nextCursor: null };
    if (path === `/api/chat/conversations/${id}` && method === 'DELETE') return undefined;
    throw new Error('Unexpected chat request');
  });
  const view = await renderScreen();
  await act(async () => view.root.findByProps({ accessibilityLabel: 'chat.room.recent' }).props.onPress());
  const recent = view.root.findByType(RecentConversations);
  const labels = recent.findAllByType(Text).map((item) => item.props.children);
  expect(labels).toContain('chat.room.deleteError');
  expect(labels).not.toContain('chat.room.product');
  expect(labels).not.toContain('hidden-product');
  expect(server.mock.calls).toEqual([['/api/chat/conversations', 'GET', 'A']]);
  await act(async () => buttonWithText(recent, 'common.retry').props.onPress());
  expect(server.mock.lastCall).toEqual([`/api/chat/conversations/${id}`, 'DELETE', 'A']);
  expect(await AsyncStorage.getItem(marker)).toBeNull();
  expect(view.root.findByType(RecentConversations).findAllByType(Text).map((item) => item.props.children)).toContain('chat.room.empty');
  await act(async () => view.unmount());
  server.mockRestore();
});

it('persists an ordinary chat when memory is disabled and stops when persistence fails', async () => {
  mockAuth.mockReturnValue({ user: { id: 'A' }, ready: true });
  const server = jest.spyOn(chatApi, 'apiChatUserRequest').mockResolvedValueOnce({ conversationId: 'saved-room', conversationVersion: 0 });
  mockMutateAsync.mockResolvedValueOnce({ answer: 'answer', products: [],
    conversation: { id: 'saved-room', version: 1, turnId: 'turn', persistenceStatus: 'stored' } });
  const view = await renderScreen();
  await act(async () => view.root.findByType(TextInput).props.onChangeText('일반 질문'));
  await act(async () => view.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress());
  expect(mockMemoryRefresh).not.toHaveBeenCalled();
  expect(mockMutateAsync).toHaveBeenCalledWith(expect.objectContaining({ conversationId: 'saved-room' }));
  server.mockRestore();
  await act(async () => view.unmount());

  useChatConversationStore.setState({ identity: undefined, conversations: {}, latest: {} });
  mockMutateAsync.mockClear();
  const unavailable = jest.spyOn(chatApi, 'apiChatUserRequest').mockRejectedValue(new ApiError('unavailable', 503, 'persistence_unavailable'));
  const failed = await renderScreen();
  await act(async () => failed.root.findByType(TextInput).props.onChangeText('저장해야 하는 질문'));
  await act(async () => failed.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress());
  expect(mockMutateAsync).not.toHaveBeenCalled();
  expect(failed.root.findAllByType(Text).some((item) => item.props.children === 'chat.ingredient.server')).toBe(true);
  unavailable.mockRestore();
  await act(async () => failed.unmount());
});

describe('selected Style recipe flow', () => {
  const recipe: ChatStyleRecipe = {
    kind: 'video', lookId: '_video-1', sourceLookId: '_video-1', recipeId: 'video:_video-1', recipeVersion: 'fixture-v1',
    title: 'Synthetic selected look', basis: 'video_metadata', reviewStatus: 'unreviewed', videoAnalyzed: false,
    synthetic: true, source: 'fixture:metadata', features: ['Fixture'], products: [], arEligible: false,
    currentStep: 0, reason: 'video_not_analyzed', steps: [
      { order: 1, zone: 'eyeshadow', title: 'Fixture eyes', guideKey: 'eyeshadow' },
      { order: 2, zone: 'lip', title: 'Fixture lips', guideKey: 'lip' },
    ],
  };
  const context = { kind: 'video' as const, lookId: '_video-1', recipeId: recipe.recipeId,
    recipeVersion: recipe.recipeVersion, currentStep: 0 };
  it('saves a recipe step before showing it and reuses the request ID after a lost response', async () => {
    mockAuth.mockReturnValue({ user: { id: 'A' }, ready: true });
    Object.assign(mockRouteParams, { recipeKind: 'video', recipeLookId: '_video-1' });
    let steps = 0;
    const server = jest.spyOn(chatApi, 'apiChatUserRequest').mockImplementation(async (path, method, _user, body) => {
      if (path === '/api/chat/conversations' && method === 'POST') return { conversationId: 'saved-room', conversationVersion: 0 };
      const update = body as { operation: string };
      if (update.operation === 'select_look') return { conversationVersion: 1 };
      if (update.operation === 'set_recipe_step' && steps++ === 0) throw new ApiError('lost', 0, 'network');
      return { conversationVersion: 3 };
    });
    mockMutateAsync.mockResolvedValueOnce({ answer: 'Recipe', products: [], styleRecipe: recipe,
      styleContext: context, conversation: { id: 'saved-room', version: 2, turnId: 'turn', persistenceStatus: 'stored' } });
    const view = await renderScreen();
    await act(async () => view.root.findByType(StyleRecipeResult).props.onStepChange(1));
    expect(view.root.findByType(StyleRecipeResult).props.result.currentStep).toBe(0);
    await act(async () => view.root.findByType(StyleRecipeResult).props.onStepChange(1));
    expect(view.root.findByType(StyleRecipeResult).props.result.currentStep).toBe(1);
    const patches = server.mock.calls.filter((call) => (call[3] as { operation?: string })?.operation === 'set_recipe_step');
    expect(patches).toHaveLength(2);
    expect(patches[0][3]).toEqual(patches[1][3]);
    expect(patches[0][3]).toMatchObject({ expectedConversationVersion: 2,
      payload: { recipeVersion: 'fixture-v1', currentStep: 1 } });
    server.mockRestore();
    await act(async () => view.unmount());
  });
  async function submit(view: ReactTestRenderer, text: string) {
    await act(async () => view.root.findByType(TextInput).props.onChangeText(text));
    await act(async () => view.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress());
  }

  it('shows linked product cards for a video eyeliner question without changing the look', async () => {
    Object.assign(mockRouteParams, { recipeKind: 'video', recipeLookId: '_video-1' });
    mockMutateAsync.mockResolvedValueOnce({ answer: 'Guide', products: [], styleRecipe: recipe, styleContext: context })
      .mockResolvedValueOnce({ answer: 'Video product: Test eyeliner', products: [{ id: 'p1', name: 'Test eyeliner', brand: 'Test', category: 'eye' }],
        styleRecipe: recipe, styleContext: context });
    const view = await renderScreen();
    await submit(view, '이 영상에서 사용한 아이라이너는 뭐야?');
    expect(mockProductsByIds).toHaveBeenCalledWith(['p1']);
    expect(view.root.findAllByType(Text).map((item) => item.props.children)).toContain('Video product: Test eyeliner');
    expect(mockMutateAsync.mock.calls[1][0].styleContext.lookId).toBe('_video-1');
    await act(async () => view.unmount());
  });

  it('shows an unlinked source product without a permanent loading state', async () => {
    Object.assign(mockRouteParams, { recipeKind: 'video', recipeLookId: '_video-1' });
    const source = { label: 'Source concealer', zone: 'foundation', mappingStatus: 'unknown' as const, catalogValid: false, arEligible: false };
    mockProductsByIds.mockReturnValue({ data: [], isPending: true, isError: false, refetch: mockRefetch });
    mockMutateAsync.mockResolvedValueOnce({ answer: 'Guide', products: [], styleRecipe: recipe, styleContext: context })
      .mockResolvedValueOnce({ answer: 'Source concealer', products: [], styleRecipe: { ...recipe, products: [source] }, styleContext: context });
    const view = await renderScreen();
    await submit(view, '이 영상에서 사용한 컨실러 제품 알려줘.');
    expect(view.root.findByType(ChatProducts).props).toMatchObject({ sourceProducts: [source], loading: false, failed: false });
    await act(async () => view.unmount());
  });

  it('uses the server product-question flag for natural wording and hides products for a guide', async () => {
    Object.assign(mockRouteParams, { recipeKind: 'video', recipeLookId: '_video-1' });
    const source = { label: 'Mascara', zone: 'mascara', productId: 'p1', mappingStatus: 'product_only' as const, catalogValid: false, arEligible: false };
    mockMutateAsync.mockResolvedValueOnce({ answer: 'Guide', products: [{ id: 'p1', name: 'Mascara', brand: 'Test', category: 'eye' }],
      styleRecipe: { ...recipe, products: [source], productQuestion: false }, styleContext: context })
      .mockResolvedValueOnce({ answer: 'Mascara', products: [{ id: 'p1', name: 'Mascara', brand: 'Test', category: 'eye' }],
        styleRecipe: { ...recipe, products: [source], productQuestion: true }, styleContext: context });
    const view = await renderScreen();
    expect(view.root.findAllByType(ChatProducts)).toHaveLength(0);
    await submit(view, '이 영상에서 쓴 마스카라 뭐야?');
    expect(view.root.findByType(ChatProducts).props.sourceProducts).toEqual([source]);
    await act(async () => view.unmount());
  });

  it('keeps the selected look for adjustments but searches when another look is requested', async () => {
    const candidates = [{ kind: 'video', lookId: '_video-1', title: 'Selected', tags: ['daily'] }];
    const alternatives = [{ kind: 'video', lookId: '_video-2', title: 'Alternative', tags: ['daily'] }];
    const otherRecipe = { ...recipe, lookId: '_video-2', sourceLookId: '_video-2', recipeId: 'video:_video-2', title: 'Alternative' };
    const otherContext = { ...context, lookId: '_video-2', recipeId: otherRecipe.recipeId };
    mockMutateAsync.mockResolvedValueOnce({ answer: 'Candidates', products: [], styleCandidates: candidates })
      .mockResolvedValueOnce({ answer: 'Guide', products: [], styleRecipe: recipe, styleContext: context })
      .mockResolvedValueOnce({ answer: 'Adjustment', products: [], styleRecipe: recipe, styleContext: context })
      .mockResolvedValueOnce({ answer: 'Other candidates', products: [], styleCandidates: alternatives })
      .mockResolvedValueOnce({ answer: 'Other guide', products: [], styleRecipe: otherRecipe, styleContext: otherContext })
      .mockResolvedValueOnce({ answer: 'Earlier looks', products: [], styleCandidates: [...alternatives, ...candidates] });
    const view = await renderScreen();
    await submit(view, '출근할 때 자연스러운 룩 추천해줘');
    await act(async () => buttonWithText(view.root, 'Selected').props.onPress());
    await submit(view, '눈은 덜 진하게 하고 립을 조금 더 강조하고 싶어.');
    expect(mockMutateAsync.mock.calls[2][0]).toMatchObject({ styleContext: { lookId: '_video-1' } });
    expect(mockMutateAsync.mock.calls[2][0].styleSearch).toBeUndefined();
    await act(async () => view.root.findByType(StyleRecipeResult).props.onStepChange(1));
    await submit(view, '다른 룩 추천해줘');
    expect(mockMutateAsync.mock.calls[3][0]).toMatchObject({ styleSearch: true, excludedStyle: { kind: 'video', lookId: '_video-1' } });
    expect(mockMutateAsync.mock.calls[3][0].styleContext).toBeUndefined();
    expect(view.root.findAllByType(Text).map((item) => item.props.children)).toContain('Alternative');
    const store = useChatConversationStore.getState();
    expect(store.conversations[store.latest.general].conversation.styleContext).toMatchObject({ lookId: '_video-1', currentStep: 1 });
    await act(async () => buttonWithText(view.root, 'Alternative').props.onPress());
    await submit(view, '아까 추천한 룩 다시 보여줘');
    expect(mockMutateAsync.mock.calls[5][0]).toMatchObject({ previousStyleSelection: { kind: 'video', lookId: '_video-2' },
      previousStyleCandidates: expect.arrayContaining([{ kind: 'video', lookId: '_video-1' }]) });
    await act(async () => view.unmount());
  });

  it('supports alternative search and earlier look references from a direct look conversation', async () => {
    Object.assign(mockRouteParams, { recipeKind: 'video', recipeLookId: '_video-1' });
    const otherRecipe = { ...recipe, lookId: '_video-2', sourceLookId: '_video-2', recipeId: 'video:_video-2', title: 'Other look' };
    const otherContext = { ...context, lookId: '_video-2', recipeId: otherRecipe.recipeId };
    const alternatives = [{ kind: 'video', lookId: '_video-2', title: 'Other look', tags: ['daily'] }];
    mockMutateAsync.mockResolvedValueOnce({ answer: 'Guide', products: [], styleRecipe: recipe, styleContext: context })
      .mockResolvedValueOnce({ answer: 'Adjustment', products: [], styleRecipe: recipe, styleContext: context })
      .mockResolvedValueOnce({ answer: 'Other candidates', products: [], styleCandidates: alternatives })
      .mockResolvedValueOnce({ answer: 'Other guide', products: [], styleRecipe: otherRecipe, styleContext: otherContext })
      .mockResolvedValueOnce({ answer: 'Earlier looks', products: [], styleCandidates: alternatives });
    const view = await renderScreen();
    await submit(view, '눈은 덜 진하게 하고 립을 강조하고 싶어.');
    expect(mockMutateAsync.mock.calls[1][0].styleContext.lookId).toBe('_video-1');
    await submit(view, '출근할 때 자연스러운 다른 룩 추천해줘');
    expect(mockMutateAsync.mock.calls[2][0]).toMatchObject({ styleSearch: true, excludedStyle: { kind: 'video', lookId: '_video-1' } });
    const store = useChatConversationStore.getState();
    expect(store.conversations[store.latest['look:video:_video-1']].conversation.styleContext?.lookId).toBe('_video-1');
    await act(async () => buttonWithText(view.root, 'Other look').props.onPress());
    expect(mockMutateAsync.mock.calls[3][0].styleContext.lookId).toBe('_video-2');
    await submit(view, '아까 추천한 룩 다시 보여줘');
    expect(mockMutateAsync.mock.calls[4][0]).toMatchObject({ styleSearch: true,
      previousStyleCandidates: expect.arrayContaining([{ kind: 'video', lookId: '_video-1' }, { kind: 'video', lookId: '_video-2' }]),
      previousStyleSelection: { kind: 'video', lookId: '_video-2' } });
    await act(async () => view.unmount());
  });

  it('keeps look suggestions, refinements and a selected look in the same conversation', async () => {
    const first = [{ kind: 'video', lookId: '_video-1', title: 'First suggestion', tags: ['daily'] }];
    const refined = [{ kind: 'video', lookId: '_video-1', title: 'Refined suggestion', tags: ['daily'] },
      { kind: 'video', lookId: '_video-2', title: 'Other suggestion', tags: ['daily'] }];
    mockMutateAsync.mockResolvedValueOnce({ answer: 'Candidates', products: [], styleCandidates: first })
      .mockResolvedValueOnce({ answer: 'Refined', products: [], styleCandidates: refined })
      .mockResolvedValueOnce({ answer: 'Guide', products: [], styleRecipe: recipe, styleContext: context })
      .mockResolvedValueOnce({ answer: 'Order', products: [], styleRecipe: recipe, styleContext: context })
      .mockResolvedValueOnce({ answer: 'Previous', products: [], styleCandidates: refined });
    const view = await renderScreen();
    await submit(view, '내일 출근할 때 자연스러운 메이크업을 하고 싶어.');
    expect(view.root.findAllByType(Text).some((node) => node.props.children === 'chat.ui.contextNotice')).toBe(false);
    expect(mockMutateAsync.mock.calls[0][0]).toMatchObject({ styleSearch: true, category: 'style' });
    await submit(view, '눈은 덜 진하게 하고 립을 조금 더 강조하고 싶어.');
    expect(mockMutateAsync.mock.calls[1][0]).toMatchObject({ styleSearch: true,
      recentMessages: expect.arrayContaining([expect.objectContaining({ text: '내일 출근할 때 자연스러운 메이크업을 하고 싶어.' })]) });
    await act(async () => buttonWithText(view.root, 'Refined suggestion').props.onPress());
    expect(mockMutateAsync.mock.calls[2][0].styleContext.lookId).toBe('_video-1');
    await submit(view, '이 룩은 어떤 순서로 하면 돼?');
    expect(mockMutateAsync.mock.calls[3][0].styleContext.lookId).toBe('_video-1');
    await submit(view, '아까 추천한 룩으로 다시 설명해줘.');
    expect(mockMutateAsync.mock.calls[4][0]).toMatchObject({ styleSearch: true,
      previousStyleCandidates: [{ kind: 'video', lookId: '_video-1' }, { kind: 'video', lookId: '_video-2' }] });
    expect(mockMutateAsync.mock.calls[4][0].styleContext).toBeUndefined();
    const room = useChatConversationStore.getState().conversations[useChatConversationStore.getState().latest.general];
    expect(room.conversation.styleContext?.lookId).toBe('_video-1');
    await act(async () => view.unmount());
  });

  it('resolves one previously suggested look separately from the current selection', async () => {
    const candidates = [{ kind: 'video', lookId: '_video-1', title: 'Previous', tags: [] }];
    mockMutateAsync.mockResolvedValueOnce({ answer: 'Candidates', products: [], styleCandidates: candidates })
      .mockResolvedValueOnce({ answer: 'Guide', products: [], styleRecipe: recipe, styleContext: context });
    const view = await renderScreen();
    await submit(view, '내일 출근할 때 자연스러운 메이크업을 하고 싶어.');
    const store = useChatConversationStore.getState();
    const id = store.latest.general;
    const room = store.conversations[id].conversation;
    await act(async () => store.setStyle({ id, ownerKey: room.ownerKey }, { kind: 'video', lookId: '_video-2', currentStep: 0 }));
    await submit(view, '아까 추천한 것으로 다시 설명해줘');
    expect(mockMutateAsync.mock.calls[1][0].styleContext).toEqual({ kind: 'video', lookId: '_video-1', currentStep: 0 });
    expect(useChatConversationStore.getState().conversations[id].conversation.styleContext?.lookId).toBe('_video-1');
    await act(async () => view.unmount());
  });

  it('keeps progress when the only previous suggestion is the selected look', async () => {
    const candidates = [{ kind: 'video', lookId: '_video-1', title: 'Previous', tags: [] }];
    mockMutateAsync.mockResolvedValueOnce({ answer: 'Candidates', products: [], styleCandidates: candidates })
      .mockResolvedValue({ answer: 'Guide', products: [], styleRecipe: recipe, styleContext: { ...context, currentStep: 1 } });
    const view = await renderScreen();
    await submit(view, '내일 출근할 때 자연스러운 메이크업을 하고 싶어.');
    await act(async () => buttonWithText(view.root, 'Previous').props.onPress());
    await submit(view, '아까 추천한 룩으로 다시 설명해줘.');
    expect(mockMutateAsync.mock.calls[2][0].styleContext).toEqual({ ...context, currentStep: 1 });
    await act(async () => view.unmount());
  });

  it('preserves condition state and compares or selects the actual listed ordinal', async () => {
    const candidates = [{ kind: 'video', lookId: '_video-1', title: 'First', tags: ['daily'] },
      { kind: 'video', lookId: '_video-2', title: 'Second', tags: ['daily'] }];
    const conditions = [{ slot: 'occasion', value: '출근' }, { slot: 'mood', value: '자연스러운' }];
    mockMutateAsync.mockResolvedValueOnce({ answer: 'Candidates', products: [], styleCandidates: candidates, styleConditions: conditions })
      .mockResolvedValueOnce({ answer: 'Compare', products: [] })
      .mockResolvedValueOnce({ answer: 'Guide', products: [], styleRecipe: { ...recipe, lookId: '_video-2', sourceLookId: '_video-2' },
        styleContext: { ...context, lookId: '_video-2' } });
    const view = await renderScreen();
    await submit(view, '출근할 때 자연스러운 룩 추천해줘');
    await submit(view, '첫 번째랑 두 번째 차이 알려줘');
    expect(mockMutateAsync.mock.calls[1][0]).toMatchObject({ styleSearch: true, styleCompare: true,
      styleConditions: conditions, previousStyleCandidates: [{ kind: 'video', lookId: '_video-1' }, { kind: 'video', lookId: '_video-2' }] });
    await submit(view, '두 번째로 할게');
    expect(mockMutateAsync.mock.calls[2][0].styleContext).toEqual({ kind: 'video', lookId: '_video-2', currentStep: 0 });
    await act(async () => view.unmount());
  });

  it('routes an explicit occasion removal to the style search with its prior state', async () => {
    const conditions = [{ slot: 'occasion', value: '출근' }, { slot: 'mood', value: '자연스러운' }];
    mockMutateAsync.mockResolvedValueOnce({ answer: 'Candidates', products: [], styleCandidates: [], styleConditions: conditions })
      .mockResolvedValueOnce({ answer: 'Refined', products: [], styleCandidates: [], styleConditions: conditions.slice(1) });
    const view = await renderScreen();
    await submit(view, '출근할 때 자연스러운 룩 추천해줘');
    await submit(view, '출근 조건은 빼줘');
    expect(mockMutateAsync.mock.calls[1][0]).toMatchObject({ styleSearch: true, styleConditions: conditions });
    const store = useChatConversationStore.getState();
    expect(store.conversations[store.latest.general].conversation.styleConditions).toEqual(conditions.slice(1));
    await act(async () => view.unmount());
  });

  it('disables stale candidates after an empty search but can recall the earlier look explicitly', async () => {
    const candidates = [{ kind: 'video', lookId: '_video-1', title: 'Earlier look', tags: [] }];
    mockMutateAsync.mockResolvedValueOnce({ answer: 'Candidates', products: [], styleCandidates: candidates })
      .mockResolvedValueOnce({ answer: 'No matches', products: [], styleCandidates: [] })
      .mockResolvedValueOnce({ answer: 'Earlier suggestions', products: [], styleCandidates: candidates });
    const view = await renderScreen();
    await submit(view, '출근할 때 자연스러운 룩 추천해줘');
    await submit(view, '출근 조건은 빼줘');
    expect(buttonWithText(view.root, 'Earlier look').props.disabled).toBe(true);
    await submit(view, '아까 추천한 룩 다시 보여줘');
    expect(mockMutateAsync.mock.calls[2][0]).toMatchObject({ styleSearch: true, previousStyleCandidates: [{ kind: 'video', lookId: '_video-1' }] });
    expect(mockMutateAsync.mock.calls[2][0].styleContext).toBeUndefined();
    await act(async () => view.unmount());
  });

  it('offers a retry for failed look search without creating suggestions', async () => {
    mockMutateAsync.mockRejectedValueOnce(new ApiError('Unavailable', 502, 'style_search_unavailable'))
      .mockResolvedValueOnce({ answer: 'No matches', products: [], styleCandidates: [] });
    const view = await renderScreen();
    await submit(view, '내일 출근할 때 자연스러운 메이크업을 하고 싶어.');
    await act(async () => buttonWithText(view.root, 'chat.ui.retry').props.onPress());
    expect(mockMutateAsync.mock.calls[1][0]).toMatchObject({ styleSearch: true });
    expect(mockMutateAsync.mock.calls[1][0].requestId).toBe(mockMutateAsync.mock.calls[0][0].requestId);
    expect(view.root.findAllByType(Text).map((item) => item.props.children)).toContain('No matches');
    await act(async () => view.unmount());
  });

  it('continues a look search after no match and sends the earlier condition', async () => {
    mockMutateAsync.mockResolvedValueOnce({ answer: 'No matches', products: [], styleCandidates: [] })
      .mockResolvedValueOnce({ answer: 'Try again', products: [], styleCandidates: [] });
    const view = await renderScreen();
    await submit(view, '내일 출근할 때 자연스러운 메이크업을 하고 싶어.');
    await submit(view, '다른 분위기로 해줘');
    expect(mockMutateAsync.mock.calls[1][0]).toMatchObject({ styleSearch: true,
      recentMessages: expect.arrayContaining([expect.objectContaining({ text: '내일 출근할 때 자연스러운 메이크업을 하고 싶어.' })]) });
    await act(async () => view.unmount());
  });

  it('automatically opens a look once and restores only general chat from the list', async () => {
    Object.assign(mockRouteParams, { recipeKind: 'video', recipeLookId: '_video-1' });
    mockMutateAsync.mockResolvedValueOnce({
      answer: 'First look answer', products: [], styleRecipe: recipe, styleContext: context,
    }).mockResolvedValueOnce({ answer: 'General guide', products: [] });
    const lookChat = await renderScreen();
    expect(lookChat.root.findAllByType(Text).some((node) => node.props.children === 'chat.entry.context')).toBe(true);
    expect(mockMutateAsync).toHaveBeenCalledTimes(1);
    expect(mockMutateAsync.mock.calls[0][0]).toMatchObject({
      category: 'style', styleContext: { kind: 'video', lookId: '_video-1' },
    });
    await act(async () => lookChat.unmount());

    delete mockRouteParams.recipeKind;
    delete mockRouteParams.recipeLookId;
    const listChat = await renderScreen();
    expect(listChat.root.findAllByType(StyleRecipeResult)).toHaveLength(0);
    expect(listChat.root.findAllByType(Text).some((node) => node.props.children === 'chat.entry.context')).toBe(false);
    await submit(listChat, '그라데이션 립 어떻게 해?');
    expect(listChat.root.findAllByType(Text).some((node) => node.props.children === 'chat.ui.contextNotice')).toBe(true);
    expect(mockMutateAsync.mock.calls[1][0].category).toBeUndefined();
    expect(mockMutateAsync.mock.calls[1][0].styleContext).toBeUndefined();
    await act(async () => listChat.unmount());

    Object.assign(mockRouteParams, { recipeKind: 'video', recipeLookId: '_video-1' });
    const reopened = await renderScreen();
    expect(mockMutateAsync).toHaveBeenCalledTimes(2);
    expect(reopened.root.findByType(StyleRecipeResult).props.result.recipeId).toBe(recipe.recipeId);
    await act(async () => reopened.unmount());
  });
  it('deduplicates simultaneous entry, separates two looks, and restores their distinct steps', async () => {
    Object.assign(mockRouteParams, { recipeKind: 'video', recipeLookId: '_video-1' });
    let resolveLook!: (value: unknown) => void;
    const other = { ...recipe, lookId: '_video-2', sourceLookId: '_video-2', recipeId: 'video:_video-2', source: 'fixture:other' };
    mockMutateAsync.mockImplementationOnce(() => new Promise((resolve) => { resolveLook = resolve; }))
      .mockResolvedValueOnce({ answer: 'Other recipe', products: [], styleRecipe: other,
        styleContext: { ...context, lookId: other.lookId, recipeId: other.recipeId } });
    const first = await renderScreen();
    const duplicate = await renderScreen();
    expect(mockMutateAsync).toHaveBeenCalledTimes(1);
    await act(async () => first.unmount());
    await act(async () => resolveLook({ answer: 'First recipe', products: [], styleRecipe: recipe, styleContext: context }));
    await act(async () => duplicate.root.findByType(StyleRecipeResult).props.onStepChange(1));

    Object.assign(mockRouteParams, { recipeLookId: '_video-2' });
    await act(async () => duplicate.update(createElement(ChatScreen)));
    expect(duplicate.root.findByType(StyleRecipeResult).props.result).toMatchObject({ source: 'fixture:other', currentStep: 0 });

    Object.assign(mockRouteParams, { recipeLookId: '_video-1' });
    await act(async () => duplicate.update(createElement(ChatScreen)));
    expect(duplicate.root.findByType(StyleRecipeResult).props.result).toMatchObject({ source: recipe.source, currentStep: 1 });
    expect(mockMutateAsync).toHaveBeenCalledTimes(2);
    await act(async () => duplicate.unmount());
  });

  it('chooses a look inside general chat and preserves the product filters for the next product request', async () => {
    mockMutateAsync.mockResolvedValueOnce({ answer: 'General candidates', products: [], chatContext: beautyContext })
      .mockResolvedValueOnce({ answer: 'General look guide', products: [] })
      .mockResolvedValueOnce({ answer: 'Selected look guide', products: [], styleRecipe: recipe, styleContext: context })
      .mockResolvedValueOnce({ answer: 'Still general', products: [] });
    const view = await renderScreen();
    await submit(view, '2만원 이하 립 추천');
    const original = useChatConversationStore.getState().latest.general;
    await submit(view, '그라데이션 립 어떻게 해?');
    await act(async () => buttonWithText(view.root, 'chat.style.chooseInline').props.onPress());
    await act(async () => buttonWithText(view.root, 'Test look').props.onPress());
    expect(mockMutateAsync.mock.calls[2][0]).toMatchObject({ category: 'style', styleContext: { lookId: '_video-1' } });
    expect(Object.keys(useChatConversationStore.getState().conversations)).toEqual([original]);
    await act(async () => buttonWithText(view.root, 'chat.ui.product').props.onPress());
    await submit(view, '그 제품들 다시 알려줘');
    expect(mockMutateAsync.mock.calls[3][0].chatContext.filters).toEqual(beautyContext.filters);
    await act(async () => view.unmount());
  });

  it('preserves the look on new chat, waits for input and shows a new tip without copying the recipe card', async () => {
    Object.assign(mockRouteParams, { recipeKind: 'video', recipeLookId: '_video-1' });
    mockMutateAsync.mockResolvedValueOnce({ answer: 'First guide', products: [], styleRecipe: recipe, styleContext: context })
      .mockResolvedValueOnce({ answer: 'New guide', products: [], styleRecipe: recipe, styleContext: context })
      .mockResolvedValueOnce({ answer: 'Fill just between the lashes and stop at the corner.', products: [],
        styleRecipe: recipe, styleContext: context });
    const view = await renderScreen();
    const key = 'look:video:_video-1';
    const original = useChatConversationStore.getState().latest[key];
    await act(async () => view.root.findByProps({ accessibilityLabel: 'chat.session.newConversation' }).props.onPress());
    const store = useChatConversationStore.getState();
    const next = store.latest[key];
    expect(next).not.toBe(original);
    expect(store.conversations[next].messages).toEqual([]);
    expect(store.conversations[next].view.activeStyle).toEqual({ kind: 'video', lookId: '_video-1', currentStep: 0 });
    expect(store.conversations[original].messages).toHaveLength(2);
    expect(mockMutateAsync).toHaveBeenCalledTimes(1);
    await submit(view, '이 룩 화장법을 단계별로 알려줘');
    await submit(view, '아이라인을 자연스럽게 하려면?');
    expect(view.root.findAllByType(StyleRecipeResult)).toHaveLength(1);
    expect(view.root.findAllByType(Text).map((item) => item.props.children)).toContain('Fill just between the lashes and stop at the corner.');
    await act(async () => view.unmount());
  });

  it('uses the selected video, keeps displayed progress in followups and leaves product context separate', async () => {
    Object.assign(mockRouteParams, { recipeKind: 'video', recipeLookId: '_video-1' });
    mockMutateAsync.mockResolvedValueOnce({ answer: 'Metadata, not video analysis', products: [], styleRecipe: recipe,
      styleContext: context, styleStatus: 'ready' }).mockResolvedValueOnce({ answer: 'Next', products: [],
      styleRecipe: { ...recipe, currentStep: 0 }, styleContext: { ...context, currentStep: 0 }, styleStatus: 'ready' });
    const view = await renderScreen();
    expect(mockMutateAsync.mock.calls[0][0]).toMatchObject({ category: 'style', styleContext: { kind: 'video', lookId: '_video-1', currentStep: 0 } });
    const roomId = useChatConversationStore.getState().latest['look:video:_video-1'];
    const beforeStep = useChatConversationStore.getState().conversations[roomId];
    Object.freeze(beforeStep.conversation.styleContext);
    Object.freeze(beforeStep.messages[1].styleRecipe);
    await act(async () => view.root.findByType(StyleRecipeResult).props.onStepChange(1));
    expect(beforeStep.conversation.styleContext?.currentStep).toBe(0);
    expect(beforeStep.messages[1].styleRecipe?.currentStep).toBe(0);
    expect(useChatConversationStore.getState().conversations[roomId].messages).not.toBe(beforeStep.messages);
    expect(view.root.findByType(StyleRecipeResult).props.result.currentStep).toBe(1);
    await submit(view, '눈 화장부터 알려줘');
    expect(mockMutateAsync.mock.calls[1][0].styleContext).toEqual({ ...context, currentStep: 1 });
    expect(mockMutateAsync.mock.calls[1][0].chatContext).toBeUndefined();
    expect(view.root.findAllByType(StyleRecipeResult).every((node) => node.props.result.currentStep === 0)).toBe(true);
    await act(async () => view.unmount());
  });
  it('retries the exact Style snapshot and request UUID after a network failure', async () => {
    Object.assign(mockRouteParams, { recipeKind: 'video', recipeLookId: '_video-1' });
    mockMutateAsync.mockRejectedValueOnce(new ApiError('network', 0)).mockResolvedValueOnce({ answer: 'Recovered', products: [],
      styleRecipe: recipe, styleContext: context });
    const view = await renderScreen();
    const snapshot = mockMutateAsync.mock.calls[0][0];
    await act(async () => buttonWithText(view.root, 'chat.ui.retry').props.onPress());
    expect(mockMutateAsync.mock.calls[1][0]).toEqual(snapshot);
    expect(view.root.findByType(StyleRecipeResult).props.result.lookId).toBe('_video-1');
    await act(async () => view.unmount());
  });
  it('does not carry prior Style progress across an authentication owner change', async () => {
    Object.assign(mockRouteParams, { recipeKind: 'video', recipeLookId: '_video-1' });
    mockMutateAsync.mockResolvedValue({ answer: 'Metadata', products: [], styleRecipe: recipe, styleContext: context });
    const view = await renderScreen();
    await act(async () => view.root.findByType(StyleRecipeResult).props.onStepChange(1));
    const oldRecipe = view.root.findByType(StyleRecipeResult).props;
    mockAuth.mockReturnValue({ user: { id: 'new-owner' }, ready: true });
    await act(async () => view.update(createElement(ChatScreen)));
    expect(view.root.findByType(StyleRecipeResult).props.result.currentStep).toBe(0);
    await act(async () => { oldRecipe.onOpenProduct('p1'); oldRecipe.onOpenAr('p1', 'p1-01'); oldRecipe.onManualAr(); });
    expect(mockPush).not.toHaveBeenCalled();
    expect(mockMutateAsync.mock.calls.at(-1)[0].styleContext).toEqual({ kind: 'video', lookId: '_video-1', currentStep: 0 });
    await act(async () => view.unmount());
  });
});

describe('server session recovery', () => {
  const context: BeautyChatContext = { ...beautyContext, session: {
    sessionId: '10000000-0000-4000-8000-000000000001',
    sessionToken: 'SYNTHETIC_CAPABILITY_NEVER_DISPLAY_12345678',
    resultSetId: '10000000-0000-4000-8000-000000000002', stateVersion: 1, expiresAt: 9999999999,
  } };
  async function send(view: ReactTestRenderer, text: string) {
    await act(async () => { view.root.findByType(TextInput).props.onChangeText(text); });
    await act(async () => { view.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress(); });
  }
  function texts(view: ReactTestRenderer) { return view.root.findAllByType(Text).map((n) => n.props.children); }

  it('G3 sends pending and complete recent turns and preserves the session on question conflict', async () => {
    const pending = { id: '10000000-0000-4000-8000-000000000009', missingSlot: 'shade', productId: 'p1',
      resultSetId: context.session!.resultSetId, createdRequestId: 'r', createdStateVersion: 1,
      expiresAt: context.session!.expiresAt, ingredientConditions: [{ ingredientName: '향료', operator: 'includes' }] };
    mockMutateAsync.mockResolvedValueOnce({ answer: '몇 호인가요?', products: [], chatContext: context,
      pendingClarification: pending, sessionStatus: 'stored', resultType: 'clarification' })
      .mockRejectedValueOnce(new ApiError('Question changed', 409, 'chat_clarification_conflict'))
      .mockResolvedValueOnce({ answer: '다시 확인', products: [], chatContext: context, sessionStatus: 'unchanged' });
    const view = await renderScreen();
    await send(view, '첫 번째 제품에 향료 있어?');
    await send(view, '03호');
    const args = mockMutateAsync.mock.calls[1][0];
    expect(args.clarificationId).toBe(pending.id);
    expect(args.recentMessages.map((m: { text: string }) => m.text)).toEqual(['첫 번째 제품에 향료 있어?', '몇 호인가요?']);
    await send(view, '첫 번째 상품 다시 확인');
    expect(mockMutateAsync.mock.calls[2][0].chatContext.session).toEqual(context.session);
    expect(mockMutateAsync.mock.calls[2][0].clarificationId).toBeUndefined();
    await act(async () => view.unmount());
  });

  it('retains the session through a general makeup explanation and the next product reference', async () => {
    mockMutateAsync.mockResolvedValueOnce({ answer: 'List', products: [], chatContext: context })
      .mockResolvedValueOnce({ answer: 'General explanation', products: [], chatContext: context, sessionStatus: 'unchanged' })
      .mockResolvedValueOnce({ answer: 'Second product', products: [], chatContext: context });
    const view = await renderScreen();
    await send(view, '립 제품 추천해줘');
    await send(view, '그라데이션 립 어떻게 해?');
    const general = mockMutateAsync.mock.calls[1][0];
    expect(general.generalMakeup).toBe(true);
    expect(general.chatContext.session).toEqual(context.session);
    expect(general.screenContext).toBeUndefined();
    expect(general.styleContext).toBeUndefined();
    expect(view.root.findAllByType(ChatProducts)).toHaveLength(0);
    await send(view, '두 번째 제품 보여줘');
    expect(mockMutateAsync.mock.calls[2][0].chatContext.session).toEqual(context.session);
    expect(mockMutateAsync.mock.calls[2][0].generalMakeup).toBeUndefined();
    await act(async () => view.unmount());
  });

  it('reopens general chat and isolates two products, their shades and the first unseeded question', async () => {
    const firstShadeEvidence = { productId: 'p1', shadeId: 'p1-01', verdict: 'UNKNOWN', status: 'unknown',
      mappingStatus: 'candidate', ingredientCoverage: 'unknown', reviewStatus: 'unreviewed',
      normalizationStatus: 'unverified', ingredients: [], reason: 'shade_required' };
    mockMutateAsync.mockResolvedValueOnce({ answer: 'Previous answer', products: [], chatContext: context })
      .mockResolvedValueOnce({ answer: 'First product answer', products: [{ id: 'p1', name: 'p1' }], ingredientResults: [firstShadeEvidence] })
      .mockResolvedValueOnce({ answer: 'Second product answer', products: [] })
      .mockResolvedValueOnce({ answer: 'Reopened product answer', products: [] });
    const view = await renderScreen();
    await send(view, '립 추천');
    const enter = async (productId?: string, shadeId?: string) => {
      Object.assign(mockRouteParams, { productId, shadeId });
      await act(async () => view.update(createElement(ChatScreen)));
    };

    await enter('p1', 'p1-01');
    expect(texts(view)).not.toContain('Previous answer');
    expect(mockMutateAsync).toHaveBeenCalledTimes(1);
    await act(async () => buttonWithText(view.root, 'chat.carousel.ingredient').props.onPress());
    expect(mockMutateAsync.mock.calls[1][0]).toMatchObject({
      screenContext: { screenId: 'product-detail', productId: 'p1', shadeId: 'p1-01' },
    });
    expect(mockMutateAsync.mock.calls[1][0].chatContext).toBeUndefined();

    await enter('p2');
    expect(texts(view)).not.toContain('First product answer');
    await send(view, '이 제품 자세히 알려줘');
    expect(mockMutateAsync.mock.calls[2][0].screenContext).toEqual({ screenId: 'product-detail', productId: 'p2' });

    await enter('p1', 'p1-02');
    expect(texts(view)).toContain('First product answer');
    expect(texts(view)).not.toContain('Second product answer');
    await send(view, '이 제품 성분은?');
    expect(mockMutateAsync.mock.calls[3][0].screenContext).toEqual({ screenId: 'product-detail', productId: 'p1', shadeId: 'p1-02' });
    expect(view.root.findByType(IngredientResult).props.results).toEqual([firstShadeEvidence]);

    await enter();
    expect(texts(view)).toContain('Previous answer');
    expect(texts(view)).not.toContain('Reopened product answer');
    await act(async () => view.unmount());
  });

  it('persists category and unsent draft in one room without sending or altering another room', async () => {
    mockMutateAsync.mockResolvedValueOnce({ answer: 'General answer', products: [], chatContext: context });
    const view = await renderScreen();
    await send(view, '립 추천');
    const general = useChatConversationStore.getState().latest.general;
    const beforeEdit = useChatConversationStore.getState().conversations[general];
    const changed = jest.fn();
    const unsubscribe = useChatConversationStore.subscribe(changed);
    await act(async () => view.root.findByType(TextInput).props.onChangeText('unsent draft'));
    await act(async () => buttonWithText(view.root, 'chat.ui.ingredient').props.onPress());
    const saved = useChatConversationStore.getState().conversations[general].view;
    expect(changed).toHaveBeenCalledTimes(2);
    expect(beforeEdit.conversation.draft).toBe('');
    expect(beforeEdit.conversation.category).toBeUndefined();
    expect(useChatConversationStore.getState().conversations[general].conversation).not.toBe(beforeEdit.conversation);
    unsubscribe();
    expect(saved.category).toBe('ingredient');
    expect(saved.sessionExpiry).toBe(context.session?.expiresAt);

    Object.assign(mockRouteParams, { productId: 'p1' });
    await act(async () => view.update(createElement(ChatScreen)));
    const other = useChatConversationStore.getState().latest['product:p1'];
    expect(useChatConversationStore.getState().conversations[other].view.category).toBe('product');
    Object.assign(mockRouteParams, { productId: undefined });
    await act(async () => view.update(createElement(ChatScreen)));
    expect(buttonWithText(view.root, 'chat.ui.ingredient').props.accessibilityState.selected).toBe(true);
    expect(view.root.findByType(TextInput).props.value).toBe('unsent draft');
    expect(mockMutateAsync).toHaveBeenCalledTimes(1);
    await act(async () => view.unmount());
  });

  it('keeps late replies in their source room and restores them from recent chats after a fresh chat', async () => {
    let finish!: (response: unknown) => void;
    mockMutateAsync.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }))
      .mockResolvedValueOnce({ answer: 'Product-only answer', products: [] });
    const view = await renderScreen();
    await send(view, 'General pending question');
    const oldId = useChatConversationStore.getState().latest.general;
    Object.assign(mockRouteParams, { productId: 'p1' });
    await act(async () => view.update(createElement(ChatScreen)));
    await send(view, 'Product question');
    await act(async () => finish({ answer: 'Late general answer', products: [], chatContext: context }));
    expect(texts(view)).not.toContain('Late general answer');

    Object.assign(mockRouteParams, { productId: undefined });
    await act(async () => view.update(createElement(ChatScreen)));
    expect(texts(view)).toContain('Late general answer');
    await act(async () => view.root.findByProps({ accessibilityLabel: 'chat.session.newConversation' }).props.onPress());
    expect(useChatConversationStore.getState().latest.general).not.toBe(oldId);
    expect(texts(view)).not.toContain('Late general answer');
    await act(async () => view.root.findByProps({ accessibilityLabel: 'chat.room.recent' }).props.onPress());
    const recent = view.root.findByType(RecentConversations);
    expect(recent.props.rooms.map((room: { conversation: { id: string } }) => room.conversation.id)).toContain(oldId);
    await act(async () => recent.props.onSelect(oldId));
    expect(texts(view)).toContain('Late general answer');
    expect(texts(view)).not.toContain('Product-only answer');
    await act(async () => view.unmount());
  });

  it('keeps the bound product when a comparison clarification is followed by just the other product name', async () => {
    Object.assign(mockRouteParams, { productId: 'p1', shadeId: 'p1-02' });
    mockMutateAsync.mockResolvedValueOnce({ answer: '어떤 제품과 비교할까요?', products: [], resultType: 'clarification' })
      .mockResolvedValueOnce({ answer: 'p1 15,000원 · p2 19,000원', products: [], resultType: 'product_detail' });
    const view = await renderScreen();
    await send(view, '다른 제품과 비교해줘');
    await send(view, 'Fwee Gloss');
    expect(mockMutateAsync.mock.calls[1][0]).toMatchObject({
      message: 'Fwee Gloss',
      screenContext: { screenId: 'product-comparison', productId: 'p1', shadeId: 'p1-02' },
    });
    expect(texts(view)).toContain('p1 15,000원 · p2 19,000원');
    await act(async () => view.unmount());
  });

  it.each(['다른 제품과 성분 비교해줘', 'Ingredient comparison with another product'])(
    'keeps ingredient comparison intent when only the other product name follows %s', async (question) => {
    Object.assign(mockRouteParams, { productId: 'p1', shadeId: 'p1-02' });
    mockMutateAsync.mockResolvedValueOnce({ answer: '어떤 제품과 비교할까요?', products: [], resultType: 'clarification' })
      .mockResolvedValueOnce({ answer: '검증된 전체 목록이 부족해요.', products: [], resultType: 'clarification' });
    const view = await renderScreen();
    await send(view, question);
    await send(view, 'Fwee Gloss');
    expect(mockMutateAsync.mock.calls[1][0].screenContext).toEqual({
      screenId: 'product-ingredient-comparison', productId: 'p1', shadeId: 'p1-02',
    });
    expect(texts(view)).toContain('검증된 전체 목록이 부족해요.');
    await act(async () => view.unmount());
  });

  it('sends a shade answer with the resolved comparison target', async () => {
    Object.assign(mockRouteParams, { productId: 'p1', shadeId: 'p1-02' });
    const ingredientComparison = {
      currentProductId: 'p1', targetProductId: 'p2', currentShadeId: 'p1-02', awaiting: 'target',
    };
    mockMutateAsync.mockResolvedValueOnce({
      answer: '퓌 글로스의 호수를 알려 주세요.', products: [], resultType: 'clarification', ingredientComparison,
    }).mockResolvedValueOnce({ answer: 'Verified comparison', products: [], resultType: 'product_detail' });
    const view = await renderScreen();
    await send(view, '퓌 글로스와 성분 비교해줘');
    await send(view, '03호');
    expect(mockMutateAsync.mock.calls[1][0].screenContext).toEqual({
      screenId: 'product-ingredient-comparison', productId: 'p1', shadeId: 'p1-02', ingredientComparison,
    });
    await act(async () => view.unmount());
  });

  it('starts a new product room with its selected shade and no automatic request', async () => {
    Object.assign(mockRouteParams, { productId: 'p1', shadeId: 'p1-02' });
    mockMutateAsync.mockResolvedValueOnce({ answer: 'Price: ₩15000', products: [], chatContext: context });
    const view = await renderScreen();
    await send(view, '이 제품 가격은?');
    const key = 'product:p1';
    const original = useChatConversationStore.getState().latest[key];
    await act(async () => view.root.findByProps({ accessibilityLabel: 'chat.session.newConversation' }).props.onPress());
    const store = useChatConversationStore.getState();
    const next = store.conversations[store.latest[key]];
    expect(next.conversation.id).not.toBe(original);
    expect(next.view.linkedProduct).toMatchObject({ productId: 'p1', shadeId: 'p1-02' });
    expect(next.view.sessionExpiry).toBeUndefined();
    expect(texts(view)).not.toContain('Price: ₩15000');
    expect(texts(view)).toContain('chat.room.pricePrompt');
    expect(mockMutateAsync).toHaveBeenCalledTimes(1);
    expect(store.conversations[original].messages).toHaveLength(2);
    await act(async () => view.unmount());
  });

  it('restores the transcript after local TTL expiry without attaching the expired session', async () => {
    const clock = jest.spyOn(Date, 'now').mockReturnValue(1000);
    try {
      const expiredSoon = { ...context, session: { ...context.session!, expiresAt: 21 } };
      mockMutateAsync.mockResolvedValueOnce({ answer: 'Saved reply', products: [], chatContext: expiredSoon })
        .mockResolvedValueOnce({ answer: 'Independent request', products: [] });
      const view = await renderScreen();
      await send(view, 'Search');
      await act(async () => view.unmount());
      clock.mockReturnValue(22000);
      const reopened = await renderScreen();
      expect(texts(reopened)).toContain('Saved reply');
      expect(texts(reopened)).toContain('chat.session.expired');
      await send(reopened, 'New search');
      expect(mockMutateAsync.mock.calls[1][0].chatContext).toBeUndefined();
      await act(async () => reopened.unmount());
    } finally { clock.mockRestore(); }
  });

  it('carries the session and version, uses a new UUID for each question, and never displays the token', async () => {
    mockMutateAsync.mockResolvedValueOnce({ answer: 'Stored first result', products: [], chatContext: context, sessionStatus: 'stored' })
      .mockResolvedValueOnce({ answer: 'Second product', products: [] });
    const view = await renderScreen();
    await send(view, '립 추천');
    await send(view, '두 번째 상품 가격');
    const first = mockMutateAsync.mock.calls[0][0];
    const next = mockMutateAsync.mock.calls[1][0];
    expect(next.chatContext.session).toEqual(context.session);
    expect(next.chatContext.candidateIds).toEqual(['p1', 'p2']);
    expect(first.requestId).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
    expect(next.requestId).not.toBe(first.requestId);
    expect(JSON.stringify(view.toJSON())).not.toContain(context.session!.sessionToken);
    await act(async () => { view.unmount(); });
  });

  it('keeps UUID, language, category and session snapshot for a network retry', async () => {
    mockMutateAsync.mockResolvedValueOnce({ answer: 'List', products: [], chatContext: context })
      .mockRejectedValueOnce(new ApiError('offline', 0, 'network'))
      .mockResolvedValueOnce({ answer: 'Retry', products: [] });
    const view = await renderScreen();
    await send(view, '추천');
    mockLanguage = 'ja';
    await act(async () => { view.update(createElement(ChatScreen)); });
    await act(async () => { buttonWithText(view.root, 'chat.ui.ingredient').props.onPress(); });
    await send(view, '성분');
    const snapshot = mockMutateAsync.mock.calls[1][0];
    mockLanguage = 'en';
    await act(async () => { view.update(createElement(ChatScreen)); });
    await act(async () => { buttonWithText(view.root, 'chat.ui.style').props.onPress(); });
    await act(async () => { buttonWithText(view.root, 'chat.ui.retry').props.onPress(); });
    expect(mockMutateAsync.mock.calls[2][0]).toEqual(snapshot);
    expect(snapshot.locale).toBe('ja');
    expect(snapshot.category).toBe('ingredient');
    await act(async () => { view.unmount(); });
  });

  it.each([
    [403, 'chat_session_forbidden', 'chat.session.forbidden'],
    [409, 'chat_session_conflict', 'chat.session.conflict'],
    [409, 'chat_request_conflict', 'chat.session.conflict'],
    [410, 'chat_session_expired', 'chat.session.expired'],
  ])('recovers %s/%s with no stale retry or candidate reference', async (status, code, key) => {
    mockMutateAsync.mockResolvedValueOnce({ answer: 'Last normal answer', products: [], chatContext: context })
      .mockRejectedValueOnce(new ApiError('failure', status as number, code as string))
      .mockResolvedValueOnce({ answer: 'Fresh search', products: [] });
    const view = await renderScreen();
    await send(view, '상품 검색');
    await send(view, '두 번째 상품');
    expect(texts(view)).toContain(key);
    expect(texts(view)).toContain('Last normal answer');
    expect(texts(view)).not.toContain('chat.ui.retry');
    expect(mockMutateAsync).toHaveBeenCalledTimes(2);
    await act(async () => { buttonWithText(view.root, 'chat.session.newSearch').props.onPress(); });
    await send(view, '립 상품 검색');
    const fresh = mockMutateAsync.mock.calls[2][0];
    expect(fresh.chatContext).toBeUndefined();
    expect(fresh.screenContext).toBeUndefined();
    expect(fresh.requestId).not.toBe(mockMutateAsync.mock.calls[1][0].requestId);
    await act(async () => { view.unmount(); });
  });

  it('distinguishes storage failure from a successful answer whose session was not saved', async () => {
    mockMutateAsync.mockResolvedValueOnce({ answer: 'List', products: [], chatContext: context })
      .mockRejectedValueOnce(new ApiError('storage', 503, 'chat_session_unavailable'))
      .mockResolvedValueOnce({ answer: 'Computed without persistence', products: [], chatContext: context, sessionStatus: 'unavailable' })
      .mockResolvedValueOnce({ answer: 'Independent', products: [] });
    const view = await renderScreen();
    await send(view, '검색');
    await send(view, '두 번째');
    expect(texts(view)).toContain('chat.session.storageError');
    const failed = mockMutateAsync.mock.calls[1][0];
    await act(async () => { buttonWithText(view.root, 'chat.ui.retry').props.onPress(); });
    expect(mockMutateAsync.mock.calls[2][0]).toEqual(failed);
    expect(texts(view)).toContain('chat.session.unavailable');
    expect(texts(view)).toContain('Computed without persistence');
    expect(texts(view)).not.toContain('chat.ui.retry');
    await send(view, '립 검색');
    expect(mockMutateAsync.mock.calls[3][0].chatContext).toBeUndefined();
    await act(async () => { view.unmount(); });
  });

  it.each([[null, 'A'], ['A', null], ['A', 'B']] as const)(
    'hides old messages, cards and ingredient evidence on identity switch %s -> %s', async (from, to) => {
      mockAuth.mockReturnValue({ user: from ? { id: from } : null, ready: true });
      mockProductsByIds.mockReturnValue({ data: [{ id: 'p1', shades: [{ id: 'p1-01' }] }],
        isPending: false, isError: false, refetch: mockRefetch });
      const refs = [{ id: 'p1', brand: 'Old brand', name: 'Old product', category: 'lip' }];
      const results = [{ productId: 'p1', shadeId: 'p1-01', verdict: 'UNKNOWN', status: 'unknown',
        mappingStatus: 'candidate', ingredientCoverage: 'unknown', reviewStatus: 'unreviewed',
        normalizationStatus: 'unverified', ingredients: [], reason: 'mapping_not_verified' }];
      mockMutateAsync.mockResolvedValueOnce({ answer: 'Old private answer', products: refs,
        ingredientResults: results, chatContext: { ...context, shadeSelections: { p1: 'p1-01' } } })
        .mockResolvedValueOnce({ answer: 'New owner search', products: [] });
      const view = await renderScreen();
      await send(view, 'Old private question');
      expect(view.root.findAllByType(ChatProducts)).toHaveLength(1);
      expect(view.root.findAllByType(IngredientResult)).toHaveLength(1);
      const oldCard = view.root.findByType(ChatProducts).props;
      await act(async () => { oldCard.onSelectShade('p1', 'p1-01'); });
      mockAuth.mockReturnValue({ user: to ? { id: to } : null, ready: true });
      await act(async () => { view.update(createElement(ChatScreen)); });
      expect(texts(view)).not.toContain('Old private question');
      expect(texts(view)).not.toContain('Old private answer');
      expect(view.root.findAllByType(ChatProducts)).toHaveLength(0);
      expect(view.root.findAllByType(IngredientResult)).toHaveLength(0);
      await act(async () => {
        oldCard.onSelectShade('p1', 'p1-01');
        oldCard.onOpenProduct('p1');
        oldCard.onOpenAr('p1', 'p1-01');
      });
      expect(mockPush).not.toHaveBeenCalled();
      await send(view, '새 립 검색');
      const fresh = mockMutateAsync.mock.calls[1][0];
      expect(fresh.expectedUserId).toBe(to);
      expect(fresh.chatContext).toBeUndefined();
      expect(fresh.screenContext).toBeUndefined();
      await act(async () => { view.unmount(); });
    }
  );

  it('does not carry failed questions or their retry across an identity switch', async () => {
    mockAuth.mockReturnValue({ user: { id: 'A' }, ready: true });
    mockMutateAsync.mockRejectedValueOnce(new ApiError('offline', 0, 'network'));
    const view = await renderScreen();
    await send(view, 'private failed question');
    expect(texts(view)).toContain('chat.ui.retry');
    mockAuth.mockReturnValue({ user: { id: 'B' }, ready: true });
    await act(async () => { view.update(createElement(ChatScreen)); });
    expect(texts(view)).not.toContain('private failed question');
    expect(texts(view)).not.toContain('chat.ui.retry');
    expect(view.root.findByType(TextInput).props.value).toBe('');
    await act(async () => { view.unmount(); });
  });

  it('preserves general history on token refresh without leaking into a look', async () => {
    mockSupabaseEnabled = true;
    mockAuth.mockReturnValue({ user: { id: 'A' }, ready: true });
    mockMutateAsync.mockResolvedValueOnce({ answer: 'Same owner answer', products: [], chatContext: context })
      .mockResolvedValueOnce({ answer: 'Look answer', products: [] });
    const view = await renderScreen();
    await act(async () => { mockAuthListener?.('INITIAL_SESSION', { user: { id: 'A' } }); });
    await send(view, 'Same owner question');
    await act(async () => { mockAuthListener?.('TOKEN_REFRESHED', { user: { id: 'A' } }); });
    expect(texts(view)).toContain('Same owner answer');
    Object.assign(mockRouteParams, { recipeKind: 'video', recipeLookId: '_video-1' });
    await act(async () => { view.update(createElement(ChatScreen)); });
    expect(texts(view)).not.toContain('Same owner question');
    expect(texts(view)).toContain('Look answer');
    delete mockRouteParams.recipeKind; delete mockRouteParams.recipeLookId;
    await act(async () => view.update(createElement(ChatScreen)));
    expect(texts(view)).toContain('Same owner answer');
    await act(async () => { view.unmount(); });
  });

  it('ignores the previous owner response and allows the new owner to send while it is pending', async () => {
    mockAuth.mockReturnValue({ user: { id: 'A' }, ready: true });
    let finish!: (value: unknown) => void;
    mockMutateAsync.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }))
      .mockResolvedValueOnce({ answer: 'B answer', products: [] });
    const view = await renderScreen();
    await send(view, 'A search');
    mockAuth.mockReturnValue({ user: { id: 'B' }, ready: true });
    await act(async () => { view.update(createElement(ChatScreen)); });
    await send(view, 'B search');
    await act(async () => { finish({ answer: 'Late A response', products: [], chatContext: context }); });
    expect(texts(view)).not.toContain('A search');
    expect(texts(view)).not.toContain('Late A response');
    expect(texts(view)).toContain('B answer');
    expect(mockMutateAsync.mock.calls[1][0].chatContext).toBeUndefined();
    await act(async () => { view.unmount(); });
  });

  it('does not discard a newer normal session when an older failed request later conflicts', async () => {
    mockMutateAsync.mockRejectedValueOnce(new ApiError('offline', 0, 'network'))
      .mockResolvedValueOnce({ answer: 'Latest normal', products: [], chatContext: context })
      .mockRejectedValueOnce(new ApiError('conflict', 409, 'chat_request_conflict'))
      .mockResolvedValueOnce({ answer: 'Current followup', products: [] });
    const view = await renderScreen();
    await send(view, 'old search');
    await send(view, 'new search');
    await act(async () => { buttonWithText(view.root, 'chat.ui.retry').props.onPress(); });
    await send(view, '두 번째 상품');
    expect(mockMutateAsync.mock.calls[3][0].chatContext.session).toEqual(context.session);
    await act(async () => { view.unmount(); });
  });

  it('does not loop after a lost bootstrap response returns a duplicate-request conflict', async () => {
    mockMutateAsync.mockRejectedValueOnce(new ApiError('offline', 0, 'network'))
      .mockRejectedValueOnce(new ApiError('duplicate', 409, 'chat_request_conflict'));
    const view = await renderScreen();
    await send(view, '립 검색');
    const first = mockMutateAsync.mock.calls[0][0];
    await act(async () => { buttonWithText(view.root, 'chat.ui.retry').props.onPress(); });
    expect(mockMutateAsync.mock.calls[1][0]).toEqual(first);
    expect(mockMutateAsync).toHaveBeenCalledTimes(2);
    expect(texts(view)).not.toContain('chat.ui.retry');
    expect(texts(view)).toContain('chat.session.newSearch');
    await act(async () => { view.unmount(); });
  });

  it('waits for authentication readiness before submitting', async () => {
    mockAuth.mockReturnValue({ user: null, ready: false });
    const view = await renderScreen();
    await send(view, '추천');
    expect(mockMutateAsync).not.toHaveBeenCalled();
    expect(view.root.findByType(TextInput).props.editable).toBe(false);
    await act(async () => { view.unmount(); });
  });

  it.each([['en', en], ['ko', ko], ['ja', ja], ['zh', zh]] as const)(
    'renders localized session and network errors in %s', async (locale, dictionary) => {
      mockLanguage = locale;
      mockDictionary = dictionary;
      for (const [status, code, key] of [
        [403, 'chat_session_forbidden', 'chat.session.forbidden'],
        [409, 'chat_session_conflict', 'chat.session.conflict'],
        [410, 'chat_session_expired', 'chat.session.expired'],
        [503, 'chat_session_unavailable', 'chat.session.storageError'],
        [0, 'network', 'chat.ingredient.network'],
      ] as const) {
        mockMutateAsync.mockRejectedValueOnce(new ApiError('error', status, code));
        const view = await renderScreen();
        await act(async () => { view.root.findByType(TextInput).props.onChangeText('query'); });
        await act(async () => { view.root.findByProps({ accessibilityLabel: dictionary['chat.ui.send'] }).props.onPress(); });
        expect(texts(view)).toContain(dictionary[key]);
        await act(async () => { view.unmount(); });
      }
    }
  );
});

describe('ingredient selection and request snapshots', () => {
  async function send(renderer: ReactTestRenderer, text: string) {
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText(text); });
    await act(async () => { renderer.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress(); });
  }
  function catalog() {
    mockProductsByIds.mockReturnValue({ data: [
      { id: 'p2', shades: [{ id: 'p2-03' }, { id: 'p2-04' }] },
      { id: 'p1', shades: [{ id: 'p1-01' }] },
    ], isPending: false, isError: false, refetch: mockRefetch });
  }
  it('passes the chosen shade from chat into the product route', async () => {
    catalog();
    mockMutateAsync.mockResolvedValueOnce({ answer: 'Answer', products: refs,
      chatContext: { ...beautyContext, shadeSelections: { p2: 'p2-04' } } });
    const view = await renderScreen();
    await send(view, '립 추천');
    await act(async () => view.root.findByType(ChatProducts).props.onOpenProduct('p2', 'p2-04'));
    expect(mockPush).toHaveBeenCalledWith({ pathname: '/product/[id]', params: { id: 'p2', shade: 'p2-04' } });
    await act(async () => view.unmount());
  });
  const refs = [{ id: 'p1', name: 'First', brand: 'B', category: 'lip' },
    { id: 'p2', name: 'Second', brand: 'B', category: 'lip' }];

  it('validates selection, retains numbering, sends the latest shade and shows server results', async () => {
    catalog();
    const results = [{ productId: 'p2', shadeId: 'p2-04', verdict: 'UNKNOWN', status: 'unknown',
      mappingStatus: 'candidate', ingredientCoverage: 'unknown', reviewStatus: 'unreviewed',
      normalizationStatus: 'unverified', ingredients: [], reason: 'mapping_not_verified' }];
    mockMutateAsync.mockResolvedValueOnce({ answer: 'Candidates', products: refs, chatContext: beautyContext })
      .mockResolvedValueOnce({ answer: 'Unknown ingredients', products: [refs[1]], ingredientResults: results });
    const renderer = await renderScreen();
    await send(renderer, '상품 추천');
    let cards = renderer.root.findByType(ChatProducts).props;
    expect(cards.products.map((p: { id: string }) => p.id)).toEqual(['p1', 'p2']);
    await act(async () => { cards.onSelectShade('p1', 'p2-03'); });
    expect(renderer.root.findByType(ChatProducts).props.selectedShades).toEqual({});
    await act(async () => { cards.onSelectShade('p2', 'p2-03'); });
    cards = renderer.root.findByType(ChatProducts).props;
    await act(async () => { cards.onSelectShade('p2', 'p2-04'); });
    await send(renderer, '두 번째 상품 성분');
    const sent = mockMutateAsync.mock.calls[1][0];
    expect(sent.chatContext.candidateIds).toEqual(['p1', 'p2']);
    expect(sent.chatContext.shadeSelections).toEqual({ p2: 'p2-04' });
    expect(sent.screenContext).toEqual({ screenId: 'chat', productId: 'p2', shadeId: 'p2-04' });
    expect(renderer.root.findByType(IngredientResult).props.results).toEqual(results);
    await act(async () => { renderer.unmount(); });
  });


  it('uses an explicitly selected product for follow-up even without a shade', async () => {
    catalog();
    const stored = { ...beautyContext, session: {
      sessionId: '10000000-0000-4000-8000-000000000001',
      sessionToken: 'SYNTHETIC_CAPABILITY_NEVER_DISPLAY_12345678',
      resultSetId: '10000000-0000-4000-8000-000000000002',
      stateVersion: 1, expiresAt: 9999999999,
    } };
    mockMutateAsync.mockResolvedValueOnce({ answer: 'Candidates', products: refs, chatContext: stored, sessionStatus: 'stored' })
      .mockResolvedValueOnce({ answer: 'Choose a shade to check ingredients', products: [], chatContext: stored });
    const renderer = await renderScreen();
    await send(renderer, '립 추천');
    const candidates = renderer.root.findByType(ChatProducts).props;
    expect(typeof candidates.onSelectProduct).toBe('function');
    await act(async () => { candidates.onSelectProduct('p2'); });
    expect(renderer.root.findAllByType(Text).some((n) => n.props.children === 'chat.carousel.chosen')).toBe(true);
    await act(async () => {
      buttonWithText(renderer.root, 'chat.carousel.ingredient').props.onPress();
    });
    const request = mockMutateAsync.mock.calls[1][0];
    expect(request.category).toBe('ingredient');
    expect(request.chatContext.selectedProductId).toBe('p2');
    expect(request.chatContext.candidateIds).toEqual(['p1', 'p2']);
    expect(request.screenContext).toEqual({ screenId: 'chat', productId: 'p2' });
    expect(request.chatContext.session).toEqual(stored.session);
    expect(JSON.stringify(renderer.toJSON())).not.toContain(stored.session.sessionToken);
    await act(async () => { renderer.unmount(); });
  });

  it('keeps retry snapshots and a later user shade against an older server response', async () => {
    catalog();
    mockMutateAsync.mockResolvedValueOnce({ answer: 'Candidates', products: refs, chatContext: beautyContext })
      .mockRejectedValueOnce(new ApiError('offline', 0, 'network'))
      .mockResolvedValueOnce({ answer: 'Retry result', products: [], chatContext: {
        ...beautyContext, shadeSelections: { p2: 'p2-03' }, selectedProductId: 'p2',
      } })
      .mockResolvedValueOnce({ answer: 'Next', products: [] });
    const renderer = await renderScreen();
    await send(renderer, '추천');
    await act(async () => { renderer.root.findByType(ChatProducts).props.onSelectShade('p2', 'p2-03'); });
    await send(renderer, '성분 확인');
    expect(renderer.root.findAllByType(Text).some((n) => n.props.children === 'chat.ingredient.network')).toBe(true);
    const original = mockMutateAsync.mock.calls[1][0];
    await act(async () => { renderer.root.findByType(ChatProducts).props.onSelectShade('p2', 'p2-04'); });
    await act(async () => { buttonWithText(renderer.root, 'chat.ui.retry').props.onPress(); });
    expect(mockMutateAsync.mock.calls[2][0]).toEqual(original);
    await send(renderer, '다시 성분');
    expect(mockMutateAsync.mock.calls[3][0].chatContext.shadeSelections).toEqual({ p2: 'p2-04' });
    await act(async () => { renderer.unmount(); });
  });

  it.each([
    [503, undefined, 'chat.ingredient.server'],
    [503, 'option_search_unavailable', 'chat.option.searchUnavailable'],
    [404, 'not_found', 'chat.ingredient.productMissing'],
    [404, 'shade_not_found', 'chat.ingredient.shadeMissing'],
  ])('localizes transport error %s/%s', async (status, code, key) => {
    mockMutateAsync.mockRejectedValueOnce(new ApiError('failure', status as number, code as string));
    const renderer = await renderScreen();
    await send(renderer, '성분');
    expect(renderer.root.findAllByType(Text).some((n) => n.props.children === key)).toBe(true);
    await act(async () => { renderer.unmount(); });
  });

  it.each([false, true])('keeps the latest shade after a pending response (G4: %s)', async (g4) => {
    catalog();
    let finish!: (value: unknown) => void;
    const optionScope = [{ productId: 'p2', shadeId: 'p2-03', optionId: 'option-03' }];
    const context = g4 ? { ...beautyContext, optionScope,
      filters: { ...beautyContext.filters, optionSearch: true } } : beautyContext;
    const optionSearch = g4 ? {
      schemaVersion: 1, status: 'PARTIAL', products: [], excludedCount: 1, omittedCount: 0,
      checkedScope: { candidateProducts: 2, candidateOptions: 2, checkedOptions: 2, unidentifiedOptions: 0,
        exhaustive: true, stoppedReason: 'COMPLETE', errors: 0 },
      items: [
        { ...optionScope[0], group: 'ELIGIBLE', sourceVersion: 'v1', synthetic: false, checks: [] },
        { productId: 'p2', shadeId: 'p2-04', optionId: 'option-04', group: 'EXCLUDED',
          sourceVersion: 'v1', synthetic: false, checks: [{ condition: 'ingredient', verdict: 'NOT_MATCH' }] },
      ],
    } : undefined;
    mockMutateAsync.mockResolvedValueOnce({ answer: 'Candidates', products: refs, chatContext: context, optionSearch })
      .mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }))
      .mockResolvedValueOnce({ answer: 'Next', products: [] });
    const renderer = await renderScreen();
    await send(renderer, '추천');
    expect(renderer.root.findByType(ChatProducts).props.optionSearch).toEqual(optionSearch);
    await act(async () => { renderer.root.findByType(ChatProducts).props.onSelectShade('p2', 'p2-03'); });
    await send(renderer, '성분');
    await act(async () => { renderer.root.findByType(ChatProducts).props.onSelectShade('p2', 'p2-04'); });
    await act(async () => { finish({ answer: 'Old shade result', products: [], chatContext: {
      ...context, candidateIds: ['p2', 'p1'], selectedProductId: 'p2', shadeSelections: { p2: 'p2-03' },
    } }); });
    await send(renderer, '두 번째 성분');
    const sent = mockMutateAsync.mock.calls[2][0];
    expect(sent.chatContext.candidateIds).toEqual(['p2', 'p1']);
    expect(sent.chatContext.shadeSelections).toEqual({ p2: 'p2-04' });
    expect(sent.screenContext).toEqual({ screenId: 'chat', productId: 'p2', shadeId: 'p2-04' });
    expect(sent.chatContext.optionScope).toEqual(g4 ? optionScope : undefined);
    await act(async () => { renderer.unmount(); });
  });
});

describe('standalone chat input', () => {
  it.each([{ refs: [] }, { refs: [{ id: 'care', brand: 'B', name: 'Care', category: 'skincare' }] }])(
    'shows the compound card panel and knowledge sources without a second generic product lookup (%#)', async ({ refs }) => {
      const compound = { planVersion: 1, goal: { wantsProducts: true }, options: [], batches: [], limitations: [] };
      mockMutateAsync.mockResolvedValueOnce({ answer: '관리 방법과 조건 확인 결과 [K1.E1]', products: refs, compound,
        knowledge: { status: 'answered', claims: [], findings: [], limitations: '', evidence: [{ id: 'K1.E1',
          documentId: 1, chunkId: 'c1', title: '근거 문서', sourceFileId: 1, sourceVersion: 'v1', blockOrder: 1,
          startUtf16: 0, endUtf16: 3, sourceLocator: {}, quote: '원문 근거', relevance: 'essential' }] } });
      const view = await renderScreen();
      await act(async () => { view.root.findByType(TextInput).props.onChangeText('건조함 관리와 제품 추천'); });
      await act(async () => { view.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress(); });
      const replies = view.root.findAllByType(Text).map((item) => item.props.children);
      expect(replies).toContain('관리 방법과 조건 확인 결과 [1]');
      expect(replies).not.toContain('원문 근거');
      await act(async () => { buttonWithText(view.root, 'chat.compound.sources').props.onPress(); });
      expect(view.root.findAllByType(Text).map((item) => item.props.children)).toContain('원문 근거');
      const cards = view.root.findByType(CompoundProductCards);
      expect(cards.props.result).toEqual(compound);
      expect(view.root.findAllByType(Text).map((item) => item.props.children)).not.toContain('chat.ui.contextNotice');
      await act(async () => { cards.props.onOpenProduct('care', undefined); });
      expect(mockPush).toHaveBeenCalledWith({ pathname: '/product/[id]', params: { id: 'care', requireShade: '1' } });
      expect(view.root.findAllByType(ChatProducts)).toHaveLength(0);
      expect(mockProductsByIds).not.toHaveBeenCalled();
      await act(async () => { view.unmount(); });
    }
  );
  it('hides answer emphasis without changing the question, stored answer, or source quote', async () => {
    const question = '질문 **그대로**';
    const answer = '답변 **강조** 그리고 **미완성';
    const quote = '원문 **그대로**';
    mockMutateAsync.mockResolvedValueOnce({ answer, products: [], knowledge: {
      status: 'answered', claims: [], findings: [], evidence: [{ id: 'E1', documentId: 1, chunkId: 'chunk',
        title: '원문', sourceFileId: 1, sourceVersion: 'v1', blockOrder: 1, startUtf16: 0, endUtf16: 10,
        sourceLocator: {}, quote, relevance: 'essential' }],
    } });
    const renderer = await renderScreen();
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText(question); });
    await act(async () => { renderer.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress(); });
    const texts = renderer.root.findAllByType(Text).map((item) => item.props.children);
    expect(texts).toContain(question);
    expect(texts).toContain('답변 강조 그리고 **미완성');
    expect(texts).toContain(quote);
    const messages = Object.values(useChatConversationStore.getState().conversations).flatMap((record) => record.messages);
    expect(messages.find((message) => message.role === 'assistant')?.text).toBe(answer);
    await act(async () => { renderer.unmount(); });
  });

  it('starts without a category and retains explicit product selection for the next request', async () => {
    mockMutateAsync.mockResolvedValue({ answer: 'Answer', products: [] });
    const renderer = await renderScreen();
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText('립 제품 추천해줘'); });
    await act(async () => { renderer.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress(); });
    expect(mockMutateAsync.mock.calls[0][0]).toEqual(expect.objectContaining({ category: undefined }));
    await act(async () => { buttonWithText(renderer.root, 'chat.ui.product').props.onPress(); });
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText('립 제품 추천해줘'); });
    await act(async () => { renderer.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress(); });
    expect(mockMutateAsync.mock.calls[1][0]).toEqual(expect.objectContaining({ category: 'product' }));
    await act(async () => { renderer.unmount(); });
  });

  it('shows a real empty result in a category-free conversation', async () => {
    mockMutateAsync.mockResolvedValueOnce({ answer: 'No products', products: [], resultType: 'empty' });
    const renderer = await renderScreen();
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText('없는 립 보여줘'); });
    await act(async () => { renderer.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress(); });
    expect(renderer.root.findAllByType(Text).some((item) => item.props.children === 'chat.ui.noProducts')).toBe(true);
    await act(async () => { renderer.unmount(); });
  });

  it('carries effective filters and candidate order into a follow-up', async () => {
    mockMutateAsync.mockResolvedValueOnce({ answer: 'Candidates', products: [], chatContext: beautyContext })
      .mockResolvedValueOnce({ answer: 'Details', products: [] });
    const renderer = await renderScreen();
    for (const text of ['2만원 이하 립 추천', '두 번째 제품 자세히']) {
      await act(async () => { renderer.root.findByType(TextInput).props.onChangeText(text); });
      await act(async () => { renderer.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress(); });
    }
    expect(mockMutateAsync.mock.calls[0][0]).toEqual(expect.objectContaining({ message: '2만원 이하 립 추천', locale: 'ko', category: undefined }));
    expect(mockMutateAsync.mock.calls[1][0]).toEqual(expect.objectContaining({ message: '두 번째 제품 자세히', locale: 'ko', category: undefined, chatContext: beautyContext }));
    await act(async () => { renderer.unmount(); });
  });

  it('retries with original context without replacing a newer successful candidate list', async () => {
    const newer = { ...beautyContext, candidateIds: ['new-1'], scopeIds: ['new-1'] };
    mockMutateAsync.mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce({ answer: 'New list', products: [], chatContext: newer })
      .mockResolvedValueOnce({ answer: 'Old retry', products: [], chatContext: beautyContext })
      .mockResolvedValueOnce({ answer: 'Latest', products: [] });
    const renderer = await renderScreen();
    for (const text of ['Old question', 'New question']) {
      await act(async () => { renderer.root.findByType(TextInput).props.onChangeText(text); });
      await act(async () => { renderer.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress(); });
    }
    await act(async () => { buttonWithText(renderer.root, 'chat.ui.retry').props.onPress(); });
    expect(mockMutateAsync.mock.calls[2][0].chatContext).toBeUndefined();
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText('그 제품 자세히'); });
    await act(async () => { renderer.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress(); });
    expect(mockMutateAsync.mock.calls[3][0].chatContext).toEqual(newer);
    await act(async () => { renderer.unmount(); });
  });

  it('shows the price and moisturizing preference for the English example', async () => {
    const renderer = await renderScreen();
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText('Recommend a moisturizing lip product under ₩20,000.'); });
    const texts = renderer.root.findAllByType(Text).map((item) => item.props.children);
    expect(texts).toContain('under ₩20,000');
    expect(texts).toContain('moisturizing');
    expect(texts).toContain('chat.ui.preferred');
    expect(mockMutateAsync).not.toHaveBeenCalled();
    await act(async () => { renderer.unmount(); });
  });

  it('shows extracted required and preferred conditions only while present in the draft', async () => {
    const renderer = await renderScreen();
    await act(async () => { renderer.root.findByType(TextInput).props.onFocus(); });
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText('립 제품 중 2만 원 이하 추천해줘, 촉촉함 우선'); });
    const texts = () => renderer.root.findAllByType(Text).map((item) => item.props.children);
    expect(texts()).toContain('chat.ui.conditions');
    expect(texts()).toContain('chat.ui.required');
    expect(texts()).toContain('chat.ui.preferred');
    expect(texts()).toContain('2만 원 이하');
    expect(mockMutateAsync).not.toHaveBeenCalled();
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText('메이크업 방법 알려줘'); });
    expect(texts()).not.toContain('chat.ui.conditions');
    expect(texts()).not.toContain('2만 원 이하');
    await act(async () => { renderer.unmount(); });
  });

  it('keeps the draft and controls available while focused, and restores the welcome area on blur or keyboard dismissal', async () => {
    const listeners: Partial<Record<'keyboardDidShow' | 'keyboardDidHide', Parameters<typeof Keyboard.addListener>[1]>> = {};
    const removals: Partial<Record<'keyboardDidShow' | 'keyboardDidHide', jest.Mock>> = {};
    const keyboardListener = jest.spyOn(Keyboard, 'addListener').mockImplementation((event, listener) => {
      const remove = jest.fn();
      if (event === 'keyboardDidShow' || event === 'keyboardDidHide') {
        listeners[event] = listener;
        removals[event] = remove;
      }
      return { remove };
    });
    const renderer = await renderScreen();
    if (Platform.OS === 'ios') {
      expect(renderer.root.findByType(KeyboardAvoidingView).props.keyboardVerticalOffset).toBe(88);
    }
    expect(renderer.root.findAllByType(Text).some((item) => item.props.children === 'chat.ui.welcomeTitle')).toBe(true);
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText('draft question'); });
    await act(async () => { renderer.root.findByType(TextInput).props.onFocus(); });
    expect(renderer.root.findAllByType(Text).some((item) => item.props.children === 'chat.ui.welcomeTitle')).toBe(false);
    expect(renderer.root.findAllByType(Text).some((item) => item.props.children === 'chat.ui.welcomeBody')).toBe(false);
    expect(renderer.root.findAllByType(Text).some((item) => item.props.children === 'chat.ui.examples')).toBe(false);
    expect(buttonWithText(renderer.root, 'chat.ui.product')).toBeTruthy();
    expect(renderer.root.findByType(TextInput).props.value).toBe('draft question');
    expect(renderer.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.disabled).toBe(false);
    await act(async () => { renderer.root.findByType(TextInput).props.onBlur(); });
    expect(renderer.root.findAllByType(Text).some((item) => item.props.children === 'chat.ui.welcomeTitle')).toBe(true);
    await act(async () => { renderer.root.findByType(TextInput).props.onFocus(); });
    expect(listeners.keyboardDidHide).toBeDefined();
    await act(async () => { listeners.keyboardDidHide?.({} as never); });
    expect(renderer.root.findAllByType(Text).some((item) => item.props.children === 'chat.ui.welcomeTitle')).toBe(true);
    expect(renderer.root.findByType(TextInput).props.value).toBe('draft question');
    await act(async () => { renderer.unmount(); });
    expect(removals.keyboardDidShow).toHaveBeenCalledTimes(1);
    expect(removals.keyboardDidHide).toHaveBeenCalledTimes(1);
    keyboardListener.mockRestore();
  });

  it('fills the draft from a problem-first example and selects a compatible consultation route', async () => {
    const renderer = await renderScreen();
    expect(buttonWithText(renderer.root, 'chat.welcome.promptA')).toBeTruthy();
    expect(buttonWithText(renderer.root, 'chat.welcome.promptB')).toBeTruthy();
    await act(async () => { buttonWithText(renderer.root, 'chat.welcome.promptB').props.onPress(); });
    expect(renderer.root.findByType(TextInput).props.value).toBe('chat.welcome.promptB');
    expect(mockMutateAsync).not.toHaveBeenCalled();
    mockMutateAsync.mockResolvedValueOnce({ answer: 'Ingredient guidance', products: [] });
    await act(async () => { renderer.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress(); });
    expect(mockMutateAsync.mock.calls[0][0].category).toBe('ingredient');
    await act(async () => { renderer.unmount(); });
  });

  it('routes a free makeup example to the advice path without a look', async () => {
    const renderer = await renderScreen();
    await act(async () => { buttonWithText(renderer.root, 'chat.welcome.promptC').props.onPress(); });
    expect(renderer.root.findByType(TextInput).props.value).toBe('chat.welcome.promptC');
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText(ko['chat.welcome.promptC']); });
    mockMutateAsync.mockResolvedValueOnce({ answer: 'Style guidance', products: [] });
    await act(async () => { renderer.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress(); });
    expect(mockMutateAsync.mock.calls[0][0].category).toBe('product');
    await act(async () => { renderer.unmount(); });
  });

  it('shows the ingredient guidance with its general-information notice', async () => {
    mockMutateAsync.mockResolvedValueOnce({ answer: 'Ingredient explanation', products: [] });
    const renderer = await renderScreen();
    await act(async () => { buttonWithText(renderer.root, 'chat.welcome.promptB').props.onPress(); });
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText('Ingredient question'); });
    await act(async () => { renderer.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress(); });
    const texts = renderer.root.findAllByType(Text).map((item) => item.props.children);
    expect(texts).toContain('Ingredient explanation');
    expect(texts).toContain('chat.ui.ingredientGeneralNotice');
    expect(texts).not.toContain('chat.ui.noProducts');
    await act(async () => { renderer.unmount(); });
  });

  it.each(['그라데이션 립 어떻게 해?', '입술 안쪽만 진하게 바르는 방법 알려줘', '초보자가 그라데이션 립 하는 법'])(
    'shows a general makeup answer directly for %s', async (question) => {
    mockMutateAsync.mockResolvedValueOnce({ answer: '입술 안쪽에 색을 올리고 바깥으로 톡톡 펴 주세요.',
      products: [{ id: 'unrelated-item' }] });
    const renderer = await renderScreen();
    await act(async () => { buttonWithText(renderer.root, 'chat.welcome.promptC').props.onPress(); });
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText(question); });
    await act(async () => { renderer.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress(); });
    const texts = renderer.root.findAllByType(Text).map((item) => item.props.children);
    expect(texts).toContain('입술 안쪽에 색을 올리고 바깥으로 톡톡 펴 주세요.');
    expect(mockPush).not.toHaveBeenCalled();
    expect(renderer.root.findAllByType(StyleRecipeResult)).toHaveLength(0);
    expect(renderer.root.findAllByType(ChatProducts)).toHaveLength(0);
    expect(mockMutateAsync.mock.calls[0][0]).toMatchObject({ category: 'product', message: question });
    await act(async () => renderer.unmount());
  });

  it('restores a failed draft and retries without duplicating the user message', async () => {
    mockMutateAsync.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({ answer: 'Answer', products: [] });
    const renderer = await renderScreen();
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText('test question'); });
    await act(async () => { renderer.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress(); });
    expect(renderer.root.findByType(TextInput).props.value).toBe('test question');
    await act(async () => { buttonWithText(renderer.root, 'chat.ui.retry').props.onPress(); });
    expect(mockMutateAsync).toHaveBeenCalledTimes(2);
    expect(renderer.root.findAllByType(Text).filter((item) => item.props.children === 'test question')).toHaveLength(1);
    expect(renderer.root.findAllByType(Text).some((item) => item.props.children === 'Answer')).toBe(true);
    await act(async () => { renderer.unmount(); });
  });

  it('marks a failed message retry unavailable while another response is pending', async () => {
    mockMutateAsync.mockRejectedValueOnce(new Error('offline'));
    const renderer = await renderScreen();
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText('test question'); });
    await act(async () => { renderer.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress(); });
    expect(renderer.root.findByType(TextInput).props.value).toBe('test question');
    expect(renderer.root.findByProps({ accessibilityRole: 'alert' }).props.children).toBe('chat.ui.error');
    mockMutateAsync.mockImplementationOnce(() => new Promise(() => {}));
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText('another question'); });
    await act(async () => { renderer.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress(); });
    const retry = buttonWithText(renderer.root, 'chat.ui.retry');
    expect(retry.props.disabled).toBe(true);
    expect(retry.props.accessibilityState).toEqual({ disabled: true });
    await act(async () => { renderer.unmount(); });
  });

  it('places an older retried answer immediately after its question', async () => {
    mockMutateAsync.mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce({ answer: 'Second answer', products: [] })
      .mockResolvedValueOnce({ answer: 'First answer', products: [] });
    const renderer = await renderScreen();
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText('First question'); });
    await act(async () => { renderer.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress(); });
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText('Second question'); });
    await act(async () => { renderer.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress(); });
    await act(async () => { buttonWithText(renderer.root, 'chat.ui.retry').props.onPress(); });
    const texts = renderer.root.findAllByType(Text).map((item) => item.props.children);
    expect(texts.indexOf('First question')).toBeLessThan(texts.indexOf('First answer'));
    expect(texts.indexOf('First answer')).toBeLessThan(texts.indexOf('Second question'));
    expect(texts.indexOf('Second question')).toBeLessThan(texts.indexOf('Second answer'));
    await act(async () => { renderer.unmount(); });
  });

  it('does not show a product-empty state for a general question in the default tab', async () => {
    mockMutateAsync.mockResolvedValueOnce({ answer: 'General answer', products: [] });
    const renderer = await renderScreen();
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText('메이크업 방법 알려줘'); });
    await act(async () => { renderer.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress(); });
    expect(renderer.root.findAllByType(Text).map((item) => item.props.children)).not.toContain('chat.ui.noProducts');
    await act(async () => { renderer.unmount(); });
  });

  it('lets the user edit a product question when no products were returned', async () => {
    mockMutateAsync.mockResolvedValueOnce({ answer: 'No matches', products: [] });
    const renderer = await renderScreen();
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText('립 제품 추천해줘'); });
    await act(async () => { renderer.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress(); });
    expect(renderer.root.findAllByType(Text).map((item) => item.props.children)).toContain('chat.ui.noProducts');
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText('다른 초안'); });
    expect(renderer.root.findAllByType(Text).map((item) => item.props.children)).not.toContain('chat.ui.editQuestion');
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText(''); });
    await act(async () => { buttonWithText(renderer.root, 'chat.ui.editQuestion').props.onPress(); });
    expect(renderer.root.findByType(TextInput).props.value).toBe('립 제품 추천해줘');
    expect(mockMutateAsync).toHaveBeenCalledTimes(1);
    await act(async () => { renderer.unmount(); });
  });

  it('prevents concurrent submissions while a response is pending', async () => {
    let finish!: (value: { answer: string; products: never[] }) => void;
    mockMutateAsync.mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    const renderer = await renderScreen();
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText('question'); });
    const send = renderer.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress;
    await act(async () => { send(); send(); });
    expect(mockMutateAsync).toHaveBeenCalledTimes(1);
    await act(async () => { finish({ answer: 'Answer', products: [] }); });
    await act(async () => { renderer.unmount(); });
  });
});

describe('standalone chat product references', () => {
  const refs = [
    { id: 'p1', brand: 'B1', name: 'N1', category: 'lip' },
    { id: 'p2', brand: 'B2', name: 'N2', category: 'lip' },
    { id: 'p1', brand: 'B1', name: 'N1', category: 'lip' },
  ];

  async function showProducts() {
    mockMutateAsync.mockResolvedValueOnce({ answer: 'Answer', products: refs });
    const renderer = await renderScreen();
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText('question'); });
    await act(async () => { renderer.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress(); });
    return renderer;
  }

  it('matches only response IDs and reports missing products', async () => {
    const found = { id: 'p2', name: 'Real product' };
    mockProductsByIds.mockReturnValue({ data: [{ id: 'unrelated' }, found], isPending: false, isError: false, refetch: mockRefetch });
    const renderer = await showProducts();
    expect(mockProductsByIds).toHaveBeenCalledWith(['p1', 'p2']);
    const props = renderer.root.findByType(ChatProducts).props;
    expect(props.products).toEqual([found]);
    expect(props.missingCount).toBe(1);
    expect(props.failed).toBe(false);
    const answer = renderer.root.findAllByType(Text).find((item) => item.props.children === 'Answer');
    expect(answer?.parent?.findAllByType(ChatProducts)).toHaveLength(0);
    await act(async () => { renderer.unmount(); });
  });

  it('hides placeholder products from an earlier lookup', async () => {
    mockProductsByIds.mockReturnValue({ data: [{ id: 'p1' }], isPending: false, isPlaceholderData: true, isError: false, refetch: mockRefetch });
    const renderer = await showProducts();
    const props = renderer.root.findByType(ChatProducts).props;
    expect(props.products).toEqual([]);
    expect(props.loading).toBe(true);
    expect(props.missingCount).toBe(0);
    await act(async () => { renderer.unmount(); });
  });

  it('exposes product lookup failure and retry', async () => {
    mockProductsByIds.mockReturnValue({ data: undefined, isPending: false, isError: true, refetch: mockRefetch });
    const renderer = await showProducts();
    const props = renderer.root.findByType(ChatProducts).props;
    expect(props.failed).toBe(true);
    expect(props.missingCount).toBe(0);
    await act(async () => { props.onRetry(); });
    expect(mockRefetch).toHaveBeenCalledTimes(1);
    await act(async () => { renderer.unmount(); });
  });

  it('keeps message and draft on product navigation while the screen stays mounted', async () => {
    mockProductsByIds.mockReturnValue({ data: [{ id: 'p1' }], isPending: false, isError: false, refetch: mockRefetch });
    const renderer = await showProducts();
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText('next draft'); });
    await act(async () => { renderer.root.findByType(ChatProducts).props.onOpenProduct('p1'); });
    expect(mockPush).toHaveBeenCalledWith({ pathname: '/product/[id]', params: { id: 'p1' } });
    await act(async () => { renderer.update(createElement(ChatScreen)); });
    expect(renderer.root.findByType(TextInput).props.value).toBe('next draft');
    expect(renderer.root.findAllByType(Text).some((item) => item.props.children === 'question')).toBe(true);
    expect(renderer.root.findAllByType(Text).some((item) => item.props.children === 'Answer')).toBe(true);
    await act(async () => { renderer.unmount(); });
  });
});

describe('structured consultation outcomes', () => {
  it('shows an empty outcome without failure or a retry and preserves follow-up scope', async () => {
    const empty = { ...beautyContext, candidateIds: [],
      filters: { ...beautyContext.filters, fragranceFree: true } };
    mockMutateAsync.mockResolvedValueOnce({ answer: '전성분 미확인', products: [],
      resultType: 'empty', chatContext: empty })
      .mockResolvedValueOnce({ answer: 'Restored', products: [], resultType: 'recommendations' });
    const renderer = await renderScreen();
    // No keyword heuristic is needed for the server's structured empty result.
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText('아까 것 중 향료 없는 것만'); });
    await act(async () => { renderer.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress(); });
    const texts = renderer.root.findAllByType(Text).map((item) => item.props.children);
    expect(texts).toContain('전성분 미확인');
    expect(texts).toContain('chat.ui.noProducts');
    expect(texts).not.toContain('chat.ui.error');
    expect(texts).not.toContain('chat.ui.retry');
    expect(renderer.root.findAllByProps({ accessibilityRole: 'alert' })).toHaveLength(0);
    expect(mockProductsByIds).not.toHaveBeenCalled();
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText('향료 조건만 빼줘.'); });
    await act(async () => { renderer.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress(); });
    expect(mockMutateAsync.mock.calls[1][0].chatContext).toEqual(empty);
    await act(async () => { renderer.unmount(); });
  });

  it('collapses unverified fragrance candidates and opens evidence for only the chosen product', async () => {
    mockProductsByIds.mockReturnValue({ data: [{ id: 'p1', shades: [] }, { id: 'p2', shades: [] }] });
    const products = [{ id: 'p1', name: 'First product' }, { id: 'p2', name: 'Second product' }];
    const results = products.map(({ id }) => ({ productId: id, verdict: 'UNKNOWN', status: 'unknown',
      mappingStatus: 'candidate', ingredientCoverage: 'unknown', reviewStatus: 'unreviewed',
      normalizationStatus: 'unverified', ingredients: [], reason: 'shade_required' }));
    mockMutateAsync.mockResolvedValueOnce({ answer: 'Unverified fragrance', products,
      fragranceSearchSummary: { total: 2, checked: 2, verifiedProductIds: [] },
      ingredientResults: results, chatContext: { ...beautyContext, filters: { ...beautyContext.filters, fragranceFree: true } } });
    const view = await renderScreen();
    await act(async () => view.root.findByType(TextInput).props.onChangeText('향료 없는 립'));
    await act(async () => view.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress());
    expect(view.root.findAllByType(ChatProducts)).toHaveLength(0);
    await act(async () => {
      const button = view.root.findAll((node) => node.props.accessibilityState?.expanded === false)[0];
      button.props.onPress();
    });
    expect(view.root.findByType(ChatProducts).props.fragrance).toBe('unknown');
    await act(async () => view.root.findByType(ChatProducts).props.onOpenEvidence('p2'));
    expect(view.root.findByType(IngredientResult).props.results).toEqual([results[1]]);
    await act(async () => view.unmount());
  });

  it('does not turn clarification into a second empty-result message', async () => {
    mockMutateAsync.mockResolvedValueOnce({ answer: '후보 번호를 알려주세요', products: [],
      resultType: 'clarification', chatContext: beautyContext });
    const renderer = await renderScreen();
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText('립 제품 중 그 제품 알려줘'); });
    await act(async () => { renderer.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress(); });
    const texts = renderer.root.findAllByType(Text).map((item) => item.props.children);
    expect(texts).toContain('후보 번호를 알려주세요');
    expect(texts).not.toContain('chat.ui.noProducts');
    expect(texts).not.toContain('chat.ui.retry');
    await act(async () => { renderer.unmount(); });
  });
  it('keeps 1000 Unicode code points in the composer without splitting emoji', async () => {
    const view = await renderScreen();
    await act(async () => view.root.findByType(TextInput).props.onChangeText('😀'.repeat(1001)));
    expect(view.root.findByType(TextInput).props.value).toBe('😀'.repeat(1000));
    await act(async () => view.root.findByType(TextInput).props.onChangeText('e\u0301'.repeat(501)));
    expect(Array.from(view.root.findByType(TextInput).props.value)).toHaveLength(1000);
    await act(async () => view.unmount());
  });

});


test('G4 forwards server option results to product cards', async () => {
  const optionSearch: NonNullable<import('@/types').ChatResponse['optionSearch']> = {
    schemaVersion: 1, status: 'PARTIAL', items: [], products: [], excludedCount: 0, omittedCount: 0,
    checkedScope: { candidateProducts: 1, candidateOptions: 1, checkedOptions: 1, unidentifiedOptions: 0, exhaustive: true, stoppedReason: 'COMPLETE', errors: 0 },
  };
  mockMutateAsync.mockResolvedValueOnce({ answer: 'Reference only', products: [{ id: 'p1' }], resultType: 'recommendations', chatContext: beautyContext, optionSearch });
  const view = await renderScreen();
  await act(async () => view.root.findByType(TextInput).props.onChangeText('립 옵션 찾아줘'));
  await act(async () => view.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress());
  expect(view.root.findByType(ChatProducts).props.optionSearch).toEqual(optionSearch);
  await act(async () => view.unmount());
});


test('G4 detail cards do not re-evaluate option conditions with product reference prices', async () => {
  mockMutateAsync.mockResolvedValueOnce({ answer: 'Product reference price', products: [{ id: 'p1' }], resultType: 'product_detail',
    chatContext: { ...beautyContext, filters: { ...beautyContext.filters, optionSearch: true } } });
  const view = await renderScreen();
  await act(async () => view.root.findByType(TextInput).props.onChangeText('첫 번째 가격은?'));
  await act(async () => view.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress());
  expect(view.root.findByType(ChatProducts).props.conditions).toEqual([]);
  await act(async () => view.unmount());
});

test('G4 search scope can be opened for a partial result without product cards', async () => {
  const optionSearch: NonNullable<import('@/types').ChatResponse['optionSearch']> = {
    schemaVersion: 1, status: 'PARTIAL', items: [], products: [], excludedCount: 0, omittedCount: 0,
    checkedScope: { candidateProducts: 1, candidateOptions: 3, checkedOptions: 2, unidentifiedOptions: 0, exhaustive: false, stoppedReason: 'TIMEOUT', errors: 1 },
  };
  mockMutateAsync.mockResolvedValueOnce({ answer: '일부 후보만 확인했어요.', products: [], resultType: 'clarification', optionSearch });
  const view = await renderScreen();
  await act(async () => view.root.findByType(TextInput).props.onChangeText('립 옵션 찾아줘'));
  await act(async () => view.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress());
  expect(view.root.findAllByType(ChatProducts)).toHaveLength(0);
  expect(view.root.findAllByType(Text).some((n) => n.props.children === 'chat.option.scopeProgress')).toBe(false);
  await act(async () => buttonWithText(view.root, 'chat.option.scopeShow').props.onPress());
  expect(view.root.findAllByType(Text).some((n) => n.props.children === 'chat.option.scopeTimeout')).toBe(true);
  expect(view.root.findAllByType(Text).some((n) => n.props.children === 'chat.option.scopeProgress')).toBe(true);
  await act(async () => view.unmount());
});

test('G4 ingredient confirmation does not show a search scope', async () => {
  const optionSearch: NonNullable<import('@/types').ChatResponse['optionSearch']> = {
    schemaVersion: 1, status: 'PARTIAL', items: [], products: [], excludedCount: 0, omittedCount: 0,
    checkedScope: { candidateProducts: 0, candidateOptions: 0, checkedOptions: 0, unidentifiedOptions: 0,
      exhaustive: false, stoppedReason: 'INGREDIENT_CONFIRMATION', errors: 0 },
  };
  mockMutateAsync.mockResolvedValueOnce({ answer: '성분명을 확인해 주세요.', products: [], resultType: 'clarification', optionSearch });
  const view = await renderScreen();
  await act(async () => view.root.findByType(TextInput).props.onChangeText('립 옵션 찾아줘'));
  await act(async () => view.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress());
  expect(view.root.findAllByType(Text).some((n) => n.props.children === '성분명을 확인해 주세요.')).toBe(true);
  expect(view.root.findAllByType(Text).some((n) => n.props.children === 'chat.option.scopeShow')).toBe(false);
  expect(view.root.findAllByType(ChatProducts)).toHaveLength(0);
  await act(async () => view.unmount());
});
