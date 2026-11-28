import AsyncStorage from '@react-native-async-storage/async-storage';
import { createElement, useEffect } from 'react';
import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import { useChatConversations } from '@/hooks/useChatConversations';
import { ApiError, apiChatUserRequest } from '@/lib/api';
import { chatRequestRecoveryKey, chatRoomDeletionKey } from '@/lib/storage';
import { useChatConversationStore } from '@/store/chatConversationStore';

jest.mock('@/lib/api', () => ({ ...jest.requireActual('@/lib/api'), apiChatUserRequest: jest.fn() }));
const request = apiChatUserRequest as jest.MockedFunction<typeof apiChatUserRequest>;
let current: ReturnType<typeof useChatConversations>;
function Harness({ userId, ownerKey }: { userId: string | null; ownerKey: string }) {
  const rooms = useChatConversations(userId, ownerKey);
  useEffect(() => { current = rooms; }, [rooms]);
  return null;
}
beforeEach(async () => {
  await AsyncStorage.clear();
  request.mockReset();
  useChatConversationStore.setState({ identity: undefined, conversations: {}, latest: {} });
  useChatConversationStore.getState().activate('A');
});

it('loads a server room, restores selected state, and loads earlier messages', async () => {
  const key = useChatConversationStore.getState().identity!.key;
  let view!: ReactTestRenderer;
  await act(async () => { view = create(createElement(Harness, { userId: 'A', ownerKey: key })); });
  request.mockResolvedValueOnce({ conversations: [{ conversationId: 'room', conversationVersion: 2,
    subject: { type: 'general' }, updatedAt: '2026-01-01T00:00:00Z' }], nextCursor: 'next' });
  await act(async () => { await current.list(); });
  expect(current.hasMore).toBe(true);
  expect(useChatConversationStore.getState().conversations.room.conversation.serverSummary).toBe(true);
  request.mockResolvedValueOnce({ conversationId: 'room', conversationVersion: 2, subject: { type: 'general' },
    context: { product: { selectedProductId: 'p1', selectedShadeId: 's1',
      historicalCandidateRefs: ['p1'], filters: { optionSearch: true } }, style: {
      kind: 'catalog', lookId: 'look1', recipeId: 'recipe1', recipeVersion: 'v1', currentStep: 1,
      conditions: [{ slot: 'color', value: 'coral' }], historicalCandidateRefs: [{ kind: 'catalog', lookId: 'look1' }],
    } },
    messages: [{ id: 'm2', role: 'assistant', text: 'answer', displayPayload: { products: [{ id: 'p1' }] } }], nextMessageCursor: 10 });
  await act(async () => { expect(await current.open('room')).toBe('room'); });
  expect(current.detailLoading).toBe(false);
  expect(current.detailError).toBe(false);
  let room = useChatConversationStore.getState().conversations.room;
  expect(room.view.linkedProduct).toMatchObject({ productId: 'p1', shadeId: 's1' });
  expect(room.conversation.styleContext).toEqual({ kind: 'catalog', lookId: 'look1', recipeId: 'recipe1',
    recipeVersion: 'v1', currentStep: 1 });
  expect(room.conversation.styleConditions).toEqual([{ slot: 'color', value: 'coral' }]);
  expect(room.messages.map((message) => message.text)).toEqual(['answer']);
  expect(room.messages[0].products?.map((product) => product.id)).toEqual(['p1']);
  expect(room.conversation.beautyContext?.session).toBeUndefined();
  expect(room.view.notice).toBe('chat.session.newSearchHint');
  request.mockResolvedValueOnce({ conversationId: 'room', messages: [{ id: 'm1', role: 'user', text: 'question' }], nextMessageCursor: null });
  await act(async () => { await current.older('room'); });
  room = useChatConversationStore.getState().conversations.room;
  expect(room.messages.map((message) => message.text)).toEqual(['question', 'answer']);
  expect(room.conversation.olderMessageCursor).toBeUndefined();
  expect(request.mock.calls[2][0]).toBe('/api/chat/conversations/room?cursor=10');
  await act(async () => view.unmount());
});

it('does not insert a late list after an account switch', async () => {
  const key = useChatConversationStore.getState().identity!.key;
  let finish!: (value: unknown) => void;
  request.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  let view!: ReactTestRenderer;
  await act(async () => { view = create(createElement(Harness, { userId: 'A', ownerKey: key })); });
  let pending!: Promise<void>;
  await act(async () => { pending = current.list(); });
  useChatConversationStore.getState().activate('B');
  const nextKey = useChatConversationStore.getState().identity!.key;
  await act(async () => { view.update(createElement(Harness, { userId: 'B', ownerKey: nextKey })); });
  await act(async () => { finish({ conversations: [{ conversationId: 'private-A' }], nextCursor: null }); await pending; });
  expect(useChatConversationStore.getState().conversations).toEqual({});
  expect(current.error).toBe(false);
  await act(async () => view.unmount());
});

const summary = (id: string) => ({ conversationId: id, conversationVersion: 2,
  subject: { type: 'general' }, updatedAt: '2026-01-01T00:00:00Z' });
const page = (...ids: string[]) => ({ conversations: ids.map(summary), nextCursor: null });
const detail = (id: string, version: number) => ({ ...summary(id), conversationVersion: version,
  context: {}, messages: [], nextMessageCursor: null });

async function mountRooms(...ids: string[]) {
  const ownerKey = useChatConversationStore.getState().identity!.key;
  let view!: ReactTestRenderer;
  await act(async () => { view = create(createElement(Harness, { userId: 'A', ownerKey })); });
  request.mockResolvedValueOnce(page(...(ids.length ? ids : ['room', 'other'])));
  await act(async () => { await current.list(); });
  return view;
}

it('finishes explicit selection while a background refresh of another room completes', async () => {
  const view = await mountRooms();
  let finishRefresh!: (value: unknown) => void;
  let finishSelection!: (value: unknown) => void;
  request.mockImplementationOnce(() => new Promise(resolve => { finishRefresh = resolve; }));
  request.mockImplementationOnce(() => new Promise(resolve => { finishSelection = resolve; }));
  let refresh!: Promise<string | undefined>;
  let selection!: Promise<string | undefined>;
  await act(async () => { refresh = current.open('other', 'refresh'); });
  await act(async () => { selection = current.open('room', 'select', () => true); });
  expect(current.detailLoading).toBe(true);
  await act(async () => { finishRefresh(detail('other', 2)); await refresh; });
  expect(current.detailLoading).toBe(true);
  await act(async () => { finishSelection(detail('room', 3)); expect(await selection).toBe('room'); });
  expect(current.detailLoading).toBe(false);
  expect(current.detailError).toBe(false);
  expect(useChatConversationStore.getState().conversations.room.conversation.serverVersion).toBe(3);
  await act(async () => view.unmount());
});

it('removes only a room confirmed missing and ignores a late listing for that room', async () => {
  const view = await mountRooms();
  useChatConversationStore.getState().resume('room');
  let finish!: (value: unknown) => void;
  request.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  let pending!: Promise<void>;
  await act(async () => { pending = current.list(); });
  request.mockRejectedValueOnce(new ApiError('Conversation not found', 404, 'not_found'));
  await act(async () => { expect(await current.open('room', 'reload')).toBeUndefined(); });
  expect(useChatConversationStore.getState().latest).toEqual({});
  await act(async () => { finish(page('room')); await pending; });
  expect(Object.keys(useChatConversationStore.getState().conversations)).toEqual(['other']);
  await act(async () => view.unmount());
});

it.each([
  [new ApiError('Gateway not found', 404), undefined],
  [new ApiError('Forbidden', 403), undefined],
  [new ApiError('Chat owner changed', 0, 'chat_owner_changed'), undefined],
  [new ApiError('Unavailable', 503), 'room'],
  [new ApiError('Network error', 0, 'network'), 'room'],
])('keeps a cached room after an unconfirmed error (%s)', async (error, opened) => {
  const view = await mountRooms();
  request.mockResolvedValueOnce(detail('room', 2));
  await act(async () => { await current.open('room'); });
  request.mockResolvedValueOnce(page('other'));
  await act(async () => { await current.list(); });
  request.mockRejectedValueOnce(error);
  await act(async () => { expect(await current.open('room')).toBe(opened); });
  expect(useChatConversationStore.getState().conversations.room.conversation.serverSummary).toBe(false);
  expect(current.error).toBe(true);
  await act(async () => view.unmount());
});

it('ignores a late room removal after the account changes', async () => {
  const view = await mountRooms();
  let reject!: (error: ApiError) => void;
  request.mockImplementationOnce(() => new Promise((_resolve, rejectPromise) => { reject = rejectPromise; }));
  let pending!: Promise<string | undefined>;
  await act(async () => { pending = current.open('room'); });
  useChatConversationStore.getState().activate('B');
  const ownerKey = useChatConversationStore.getState().identity!.key;
  await act(async () => { view.update(createElement(Harness, { userId: 'B', ownerKey })); });
  request.mockResolvedValueOnce(page('new-room'));
  await act(async () => { await current.list(); });
  await act(async () => { reject(new ApiError('Conversation not found', 404, 'not_found')); await pending; });
  expect(Object.keys(useChatConversationStore.getState().conversations)).toEqual(['new-room']);
  expect(current.error).toBe(false);
  await act(async () => view.unmount());
});

it('restores a conflicted room without resending the request or discarding the draft', async () => {
  const view = await mountRooms();
  request.mockResolvedValueOnce(detail('room', 2));
  await act(async () => { await current.open('room'); });
  const state = useChatConversationStore.getState();
  const before = state.conversations.room.conversation;
  state.setDraft(before, 'Keep this draft');
  state.setNotice(before, 'chat.session.conflict');
  request.mockResolvedValueOnce(detail('room', 3));
  await act(async () => { expect(await current.open('room', 'reload')).toBe('room'); });
  const after = useChatConversationStore.getState().conversations.room.conversation;
  expect(after).toMatchObject({ draft: 'Keep this draft', serverVersion: 3, generation: before.generation + 1 });
  expect(request.mock.calls.slice(1).map(([path, method]) => [path, method])).toEqual([
    ['/api/chat/conversations/room', 'GET'], ['/api/chat/conversations/room', 'GET'],
  ]);
  await act(async () => view.unmount());
});

it('ignores an earlier message page from before a room reload', async () => {
  const view = await mountRooms();
  request.mockResolvedValueOnce({ ...detail('room', 2), nextMessageCursor: 10 });
  await act(async () => { await current.open('room'); });
  let finish!: (value: unknown) => void;
  request.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  let pending!: Promise<void>;
  await act(async () => { pending = current.older('room'); });
  request.mockResolvedValueOnce({ ...detail('room', 3), nextMessageCursor: 10 });
  await act(async () => { await current.open('room', 'reload'); });
  await act(async () => {
    finish({ ...detail('room', 2), messages: [{ id: 'old-page', role: 'user', text: 'Old result' }] });
    await pending;
  });
  expect(useChatConversationStore.getState().conversations.room.messages).toEqual([]);
  await act(async () => view.unmount());
});

it.each([
  new ApiError('Response lost', 0, 'network'),
  new ApiError('Deletion incomplete', 503, 'deletion_incomplete'),
  new ApiError('Deletion unconfirmed', 404, 'not_found'),
])('preserves the room for retry when DELETE fails (%s)', async (error) => {
  const view = await mountRooms();
  request.mockRejectedValueOnce(error).mockResolvedValueOnce(undefined);
  await act(async () => { await current.remove('room'); });
  expect(useChatConversationStore.getState().conversations.room.conversation.deletionState).toBe('failed');
  await act(async () => { expect(await current.open('room')).toBeUndefined(); });
  await act(async () => { await current.remove('room'); });
  expect(request.mock.calls.slice(1)).toEqual([
    ['/api/chat/conversations/room', 'DELETE', 'A'],
    ['/api/chat/conversations/room', 'DELETE', 'A'],
  ]);
  expect(Object.keys(useChatConversationStore.getState().conversations)).toEqual(['other']);
  await act(async () => view.unmount());
});

it('prevents duplicate deletion and ignores late details and listings for the room', async () => {
  const view = await mountRooms();
  let finishDetail!: (value: unknown) => void;
  let finishDelete!: (value: unknown) => void;
  request.mockImplementationOnce(() => new Promise((resolve) => { finishDetail = resolve; }))
    .mockImplementationOnce(() => new Promise((resolve) => { finishDelete = resolve; }));
  let opening!: Promise<string | undefined>;
  let deleting!: Promise<void>;
  await act(async () => {
    opening = current.open('room', 'reload');
    deleting = current.remove('room');
    await current.remove('room');
  });
  expect(useChatConversationStore.getState().conversations.room.conversation.deletionState).toBe('pending');
  expect(request.mock.calls.filter(([, method]) => method === 'DELETE')).toHaveLength(1);
  await act(async () => {
    finishDetail(detail('room', 3));
    expect(await opening).toBeUndefined();
    view.unmount();
  });
  await act(async () => { finishDelete(undefined); await deleting; });
  const ownerKey = useChatConversationStore.getState().identity!.key;
  let nextView!: ReactTestRenderer;
  await act(async () => { nextView = create(createElement(Harness, { userId: 'A', ownerKey })); });
  request.mockResolvedValueOnce(page('room', 'other'));
  await act(async () => { await current.list(); });
  expect(Object.keys(useChatConversationStore.getState().conversations)).toEqual(['other']);
  await act(async () => nextView.unmount());
});

it('isolates an old deletion response from the new account', async () => {
  const view = await mountRooms();
  let finish!: (value: unknown) => void;
  request.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  let deleting!: Promise<void>;
  await act(async () => { deleting = current.remove('room'); });
  useChatConversationStore.getState().activate('B');
  const ownerKey = useChatConversationStore.getState().identity!.key;
  await act(async () => { view.update(createElement(Harness, { userId: 'B', ownerKey })); });
  request.mockResolvedValueOnce(page('room'));
  await act(async () => { await current.list(); });
  await act(async () => { finish(undefined); await deleting; });
  expect(useChatConversationStore.getState().conversations.room.conversation).toMatchObject({ ownerKey, userId: 'B' });
  expect(useChatConversationStore.getState().removedServerRooms.size).toBe(0);
  await act(async () => view.unmount());
});

it('fences local copies when a create response binds an ID from the server list', async () => {
  const view = await mountRooms();
  const store = useChatConversationStore.getState();
  const ownerKey = store.identity!.key;
  const local = store.open({ type: 'general' }, true)!;
  const during = store.open({ type: 'general' }, true)!;
  const after = store.open({ type: 'general' }, true)!;
  store.bindServerRoom({ id: local, ownerKey }, 'room', 2);
  let finish!: (value: unknown) => void;
  request.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  let deleting!: Promise<void>;
  await act(async () => { deleting = current.remove('room'); });
  store.bindServerRoom({ id: during, ownerKey }, 'room', 2);
  expect(useChatConversationStore.getState().conversations[local].conversation.deletionState).toBe('pending');
  expect(useChatConversationStore.getState().conversations[during].conversation.deletionState).toBe('pending');
  await act(async () => { finish(undefined); await deleting; });
  store.bindServerRoom({ id: after, ownerKey }, 'room', 2);
  expect(Object.keys(useChatConversationStore.getState().conversations)).toEqual(['other']);
  await act(async () => view.unmount());
});

it('updates list order without advancing a loaded room before its detail is refreshed', async () => {
  const view = await mountRooms();
  request.mockResolvedValueOnce(detail('room', 2));
  await act(async () => { await current.open('room'); });
  const store = useChatConversationStore.getState();
  store.setDraft(store.conversations.room.conversation, 'Draft');
  store.resume('other');
  const updatedAt = '2026-02-01T00:00:00Z';
  request.mockResolvedValueOnce({ conversations: [{ ...summary('room'), conversationVersion: 3, updatedAt }], nextCursor: 'page/2' });
  await act(async () => { await current.list(); });
  let room = useChatConversationStore.getState().conversations.room;
  expect(room.updatedAt).toBe(Date.parse(updatedAt));
  expect(room.conversation.serverVersion).toBe(2);
  request.mockResolvedValueOnce(page('older'));
  await act(async () => { await current.list(true); });
  expect(request.mock.lastCall?.[0]).toBe('/api/chat/conversations?cursor=page%2F2');
  request.mockResolvedValueOnce(page('other'))
    .mockResolvedValueOnce({ ...detail('room', 3), messages: [{ id: 'remote', role: 'assistant', text: 'New from another device' }] });
  await act(async () => { await Promise.all([current.refresh('room'), current.refresh('room')]); });
  room = useChatConversationStore.getState().conversations.room;
  expect(room.conversation).toMatchObject({ draft: 'Draft', serverVersion: 3 });
  expect(room.updatedAt).toBe(Date.parse(updatedAt));
  expect(room.messages.map(({ text }) => text)).toEqual(['New from another device']);
  expect(useChatConversationStore.getState().latest.general).toBe('other');
  expect(useChatConversationStore.getState().conversations.older).toBeDefined();
  expect(request.mock.calls.slice(4)).toEqual([
    ['/api/chat/conversations', 'GET', 'A'],
    ['/api/chat/conversations/room', 'GET', 'A'],
  ]);
  await act(async () => view.unmount());
});

it('opens a saved room while a background list is still loading', async () => {
  const view = await mountRooms();
  let finishList!: (value: unknown) => void;
  request.mockImplementationOnce(() => new Promise((resolve) => { finishList = resolve; }))
    .mockResolvedValueOnce(detail('room', 2));
  let refreshing!: Promise<void>;
  await act(async () => { refreshing = current.refresh(); });
  await act(async () => { expect(await current.open('room')).toBe('room'); });
  await act(async () => { finishList(page('other')); await refreshing; });
  expect(useChatConversationStore.getState().conversations.room.conversation.serverSummary).toBe(false);
  await act(async () => view.unmount());
});

it('keeps list summaries across detail loads and ignores stale or foreign room metadata', async () => {
  const view = await mountRooms();
  const listSummary = { titleTopic: 'product', previewTopics: ['hydration', 'price'] };
  request.mockResolvedValueOnce({ conversations: [{ ...summary('room'), listSummary }], nextCursor: null })
    .mockResolvedValueOnce(detail('room', 3));
  await act(async () => { await current.list(); await current.open('room'); });
  expect(useChatConversationStore.getState().conversations.room.listSummary).toEqual(listSummary);
  request.mockResolvedValueOnce({ conversations: [{ ...summary('room'), listSummary: { titleTopic: 'look', previewTopics: [] } }] });
  await act(async () => { await current.list(); });
  const store = useChatConversationStore.getState();
  store.mergeServerRooms('other-owner', [{ ...summary('other'), subject: { type: 'general' },
    listSummary: { titleTopic: 'ingredient', previewTopics: [] } }]);
  expect(useChatConversationStore.getState().conversations.room.listSummary).toEqual(listSummary);
  expect(useChatConversationStore.getState().conversations.other.listSummary).toBeUndefined();
  await act(async () => view.unmount());
});

it('recovers an unconfirmed deletion after a restart and retries it only on request', async () => {
  const roomId = 'dc5e680d-46e0-43a8-ab99-80422c19491c';
  const marker = chatRoomDeletionKey('A', roomId);
  const otherMarker = chatRoomDeletionKey('B', 'fcd07c81-3046-4b5f-b85f-682d506c5bb2');
  const firstView = await mountRooms(roomId, 'other');
  let markerAtRequest: string | null = null;
  request.mockImplementationOnce(async () => {
    markerAtRequest = await AsyncStorage.getItem(marker);
    throw new ApiError('Response lost', 0, 'network');
  });
  await act(async () => { await current.remove(roomId); });
  expect(markerAtRequest).toBe('1');
  expect(await AsyncStorage.getAllKeys()).toEqual([marker]);
  await act(async () => firstView.unmount());
  useChatConversationStore.setState({ identity: undefined, conversations: {}, latest: {} });
  useChatConversationStore.getState().activate('A');
  await AsyncStorage.setItem(otherMarker, '1');

  const view = await mountRooms('other');
  const store = useChatConversationStore.getState();
  expect(Object.keys(store.conversations).sort()).toEqual([roomId, 'other'].sort());
  expect(store.conversations[roomId]).toMatchObject({
    messages: [], recoveredDeletion: true, conversation: { deletionState: 'failed', serverId: roomId },
  });
  expect(request.mock.calls.filter(([, method]) => method === 'DELETE')).toHaveLength(1);
  await act(async () => { expect(await current.open(roomId)).toBeUndefined(); });
  expect(request.mock.lastCall?.[0]).toBe('/api/chat/conversations');

  const pendingRequest = 'e304ac35-aa31-4f52-861d-f3ba4983baf5';
  await AsyncStorage.setItem(chatRequestRecoveryKey('A', roomId, pendingRequest), '1');
  await AsyncStorage.setItem(chatRequestRecoveryKey('B', roomId, pendingRequest), '1');
  request.mockResolvedValueOnce(undefined);
  await act(async () => { await current.remove(roomId); });
  expect(request.mock.lastCall).toEqual([`/api/chat/conversations/${roomId}`, 'DELETE', 'A']);
  expect(Object.keys(useChatConversationStore.getState().conversations)).toEqual(['other']);
  expect(await AsyncStorage.getItem(marker)).toBeNull();
  expect(await AsyncStorage.getItem(otherMarker)).toBe('1');
  expect(await AsyncStorage.getItem(chatRequestRecoveryKey('A', roomId, pendingRequest))).toBeNull();
  expect(await AsyncStorage.getItem(chatRequestRecoveryKey('B', roomId, pendingRequest))).toBe('1');
  await act(async () => view.unmount());
});

it('preserves the room and skips DELETE if its recovery marker cannot be saved', async () => {
  const view = await mountRooms();
  jest.mocked(AsyncStorage.setItem).mockRejectedValueOnce(new Error('Disk unavailable'));
  await act(async () => { await current.remove('room'); });
  expect(request.mock.calls.filter(([, method]) => method === 'DELETE')).toHaveLength(0);
  expect(useChatConversationStore.getState().conversations.room.conversation.deletionState).toBe('failed');
  expect(await AsyncStorage.getAllKeys()).toEqual([]);
  await act(async () => view.unmount());
});

const recoveringId = '51fcd7ec-aa21-45d5-854e-762897767966';
const statusPath = `/api/chat/conversations/room/requests/${recoveringId}`;

it('rechecks a restored pending request and only finishes recovery with a current committed detail', async () => {
  const marker = chatRequestRecoveryKey('A', 'room', recoveringId);
  await AsyncStorage.setItem(marker, '1');
  const view = await mountRooms();
  request.mockResolvedValueOnce(detail('room', 2))
    .mockResolvedValueOnce({ requestId: recoveringId, status: 'IN_PROGRESS' });
  await act(async () => { expect(await current.open('room')).toBe('room'); });
  expect(useChatConversationStore.getState().conversations.room.conversation.requestRecovery?.status).toBe('in_progress');
  expect(request.mock.lastCall).toEqual([statusPath, 'GET', 'A']);

  const committed = { requestId: recoveringId, status: 'COMMITTED', response: {
    conversation: { id: 'room', version: 3, persistenceStatus: 'stored' },
  } };
  request.mockResolvedValueOnce(committed).mockResolvedValueOnce(detail('room', 2));
  await act(async () => { await current.recover('room'); });
  expect(useChatConversationStore.getState().conversations.room.conversation.requestRecovery?.status).toBe('unconfirmed');
  expect(await AsyncStorage.getItem(marker)).toBe('1');

  const beforeRefresh = request.mock.calls.length;
  request.mockImplementation(async (path) => {
    if (path === '/api/chat/conversations') return page('room');
    if (path === statusPath) return committed;
    return { ...detail('room', 3), messages: [{ id: 'complete', role: 'assistant', text: 'Committed answer' }] };
  });
  await act(async () => { await current.refresh('room'); });
  const room = useChatConversationStore.getState().conversations.room;
  expect(room.conversation.requestRecovery).toBeUndefined();
  expect(room.messages.map(({ text }) => text)).toEqual(['Committed answer']);
  expect(await AsyncStorage.getItem(marker)).toBeNull();
  expect(request.mock.calls.slice(beforeRefresh).map(([, method]) => method)).toEqual(['GET', 'GET', 'GET']);
  await act(async () => view.unmount());
});

it('isolates late request status responses after an account switch', async () => {
  const marker = chatRequestRecoveryKey('A', 'room', recoveringId);
  await AsyncStorage.setItem(marker, '1');
  const view = await mountRooms();
  let finish!: (value: unknown) => void;
  request.mockResolvedValueOnce(detail('room', 2))
    .mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  let opening!: Promise<string | undefined>;
  await act(async () => { opening = current.open('room'); });
  useChatConversationStore.getState().activate('B');
  const ownerKey = useChatConversationStore.getState().identity!.key;
  await act(async () => { view.update(createElement(Harness, { userId: 'B', ownerKey })); });
  request.mockResolvedValueOnce(page('room')).mockResolvedValueOnce(detail('room', 2));
  await act(async () => { await current.list(); await current.open('room'); });
  await act(async () => {
    finish({ requestId: recoveringId, status: 'INTERRUPTED' });
    expect(await opening).toBeUndefined();
  });
  expect(useChatConversationStore.getState().conversations.room.conversation.requestRecovery).toBeUndefined();
  expect(await AsyncStorage.getItem(marker)).toBe('1');
  await act(async () => view.unmount());
});

it('does not apply request recovery after the room selection is cancelled', async () => {
  const marker = chatRequestRecoveryKey('A', 'room', recoveringId);
  await AsyncStorage.setItem(marker, '1');
  const view = await mountRooms();
  let finish!: (value: unknown) => void;
  request.mockResolvedValueOnce(detail('room', 2))
    .mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  let selected = true;
  let opening!: Promise<string | undefined>;
  await act(async () => { opening = current.open('room', 'select', () => selected); });
  selected = false;
  await act(async () => {
    finish({ requestId: recoveringId, status: 'COMMITTED', response: {
      conversation: { id: 'room', version: 3, persistenceStatus: 'stored' },
    } });
    expect(await opening).toBeUndefined();
  });
  expect(request.mock.lastCall).toEqual([statusPath, 'GET', 'A']);
  expect(useChatConversationStore.getState().conversations.room.conversation.requestRecovery?.status).toBe('unconfirmed');
  expect(await AsyncStorage.getItem(marker)).toBe('1');
  await act(async () => view.unmount());
});


it('restores sale option display and selected option without an AR shade', async () => {
  const saleOptions = { selections: [{ productId: 'p1', optionId: 'sale-1', shadeId: null,
    productName: 'Product', brand: 'Brand', shadeName: 'Sale option' }], batches: [], failedProductIds: [] };
  const key = useChatConversationStore.getState().identity!.key;
  let view!: ReactTestRenderer;
  await act(async () => { view = create(createElement(Harness, { userId: 'A', ownerKey: key })); });
  request.mockResolvedValueOnce({ conversations: [{ conversationId: 'room', conversationVersion: 2, subject: { type: 'general' }, updatedAt: '2026-01-01T00:00:00Z' }], nextCursor: null });
  await act(async () => { await current.list(); });
  request.mockResolvedValueOnce({ conversationId: 'room', conversationVersion: 2, subject: { type: 'product', productId: 'p1' },
    context: { product: { selectedProductId: 'p1', selectedOptionId: 'sale-1', filters: {} } },
    messages: [{ id: 'm', role: 'assistant', text: 'option', displayPayload: { ownedLookOptions: saleOptions } }] });
  await act(async () => { expect(await current.open('room')).toBe('room'); });
  const room = useChatConversationStore.getState().conversations.room;
  expect(room.view.linkedProduct?.optionId).toBe('sale-1');
  expect(room.messages[0].ownedLookOptions).toEqual(saleOptions);
  expect(room.messages[0].ownedLookOptions?.selections[0].shadeId).toBeNull();
  expect(current.detailLoading).toBe(false);
  await act(async () => { view.unmount(); });
});

it('cancels the exact pending request and releases it only after server acknowledgement', async () => {
  const store = useChatConversationStore.getState;
  const id = store().open({ type: 'general' })!;
  let room = store().conversations[id].conversation;
  store().bindServerRoom(room, 'server-room', 0);
  room = store().conversations[id].conversation;
  const ticket = store().beginRequest(room, { automatic: false, revision: 0, generation: room.generation,
    styleRevision: 0, args: { message: 'old question', locale: 'ko', requestId: 'old-request', expectedUserId: 'A' } })!;
  let view!: ReactTestRenderer;
  await act(async () => { view = create(createElement(Harness, { userId: 'A', ownerKey: room.ownerKey })); });
  let finish!: (value: unknown) => void;
  request.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  let pending!: Promise<void>;
  await act(async () => { pending = current.cancel(id); });
  expect(store().conversations[id].conversation.requestRecovery?.status).toBe('checking');
  expect(store().completeRequest(ticket, { answer: 'late', products: [] }, 'old')).toBe(false);
  await act(async () => { finish({requestId: 'old-request', status: 'INTERRUPTED', conversationVersion: 0}); await pending; });
  expect(request.mock.calls[0].slice(0, 3)).toEqual(['/api/chat/conversations/server-room/requests/old-request/cancel', 'POST', 'A']);
  expect(store().conversations[id].conversation.requestRecovery).toBeUndefined();
  expect(store().conversations[id].view.notice).toBe('chat.cancel.done');
  expect(store().conversations[id].view.draft).toBe('old question');
  await act(async () => view.unmount());
});

it.each(['committed', 'lost', 'account-change'])('resolves cancellation %s without inventing success', async (mode) => {
  const store = useChatConversationStore.getState;
  const id = store().open({ type: 'general' })!;
  let room = store().conversations[id].conversation;
  store().bindServerRoom(room, 'server-room', 0);
  room = store().conversations[id].conversation;
  store().beginRequest(room, { automatic: false, revision: 0, generation: room.generation,
    styleRevision: 0, args: { message: 'question', locale: 'ko', requestId: 'rid', expectedUserId: 'A' } });
  let view!: ReactTestRenderer;
  await act(async () => { view = create(createElement(Harness, { userId: 'A', ownerKey: room.ownerKey })); });
  if (mode === 'committed') {
    request.mockResolvedValueOnce({requestId:'rid',status:'COMMITTED',conversationVersion:1});
    request.mockResolvedValueOnce({requestId:'rid',status:'COMMITTED',response:{conversation:{id:'server-room',version:1,persistenceStatus:'stored'}}});
    request.mockResolvedValueOnce({conversationId:'server-room',conversationVersion:1,subject:{type:'general'},context:{},messages:[{id:'answer',role:'assistant',text:'completed',createdAt:'now',displayPayload:{consultation:{status:'partial',hasPendingInput:true,displaySelectionRequired:false,displayChoices:[]}}}]});
    await act(async () => { await current.cancel(id); });
    expect(store().conversations[id].messages[0].text).toBe('completed');
    expect(store().conversations[id].messages[0].consultation).toMatchObject({status:'partial',hasPendingInput:true});
    expect(store().conversations[id].view.notice).not.toBe('chat.cancel.done');
  } else if (mode === 'lost') {
    request.mockRejectedValueOnce(new ApiError('offline',0));
    request.mockResolvedValueOnce({requestId:'rid',status:'IN_PROGRESS'});
    await act(async () => { await current.cancel(id); });
    expect(store().conversations[id].conversation.requestRecovery?.status).toBe('in_progress');
    expect(store().conversations[id].view.notice).not.toBe('chat.cancel.done');
  } else {
    let finish!: (value: unknown) => void;
    request.mockImplementationOnce(() => new Promise(resolve => { finish=resolve; }));
    let pending!: Promise<void>;
    await act(async () => { pending=current.cancel(id); });
    await act(async () => { store().activate('B'); finish({requestId:'rid',status:'INTERRUPTED',conversationVersion:0}); await pending; });
    expect(store().conversations[id]).toBeUndefined();
  }
  await act(async () => view.unmount());
});

it('opens saved consultation summary without losing its result choices or staying in loading', async () => {
  const key=useChatConversationStore.getState().identity!.key;
  let view!:ReactTestRenderer;
  await act(async()=>{view=create(createElement(Harness,{userId:'A',ownerKey:key}));});
  const consultation={status:'partial',hasPendingInput:true,displaySelectionRequired:true,
    displayChoices:[{taskId:'task-a',label:'첫 요청'},{taskId:'task-b',label:'다음 요청'}],selectedTaskId:null};
  request.mockResolvedValueOnce({conversations:[{conversationId:'room',conversationVersion:1,subject:{type:'general'}}],nextCursor:null});
  await act(async()=>{await current.list();});
  request.mockResolvedValueOnce({conversationId:'room',conversationVersion:1,subject:{type:'general'},context:{},messages:[
    {id:'reply',role:'assistant',text:'확인할 결과를 골라주세요',displayPayload:{consultation,products:[]}}]});
  await act(async()=>{await current.open('room');});
  expect(current.detailLoading).toBe(false);
  expect(useChatConversationStore.getState().conversations.room.messages[0].consultation).toEqual(consultation);
  await act(async()=>{view.unmount();});
});
