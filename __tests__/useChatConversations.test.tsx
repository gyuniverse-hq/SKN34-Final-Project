import { createElement } from 'react';
import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import { useChatConversations } from '@/hooks/useChatConversations';
import { apiChatUserRequest } from '@/lib/api';
import { useChatConversationStore } from '@/store/chatConversationStore';

jest.mock('@/lib/api', () => ({ apiChatUserRequest: jest.fn() }));
const request = apiChatUserRequest as jest.MockedFunction<typeof apiChatUserRequest>;
let current: ReturnType<typeof useChatConversations>;
function Harness({ userId, ownerKey }: { userId: string | null; ownerKey: string }) {
  current = useChatConversations(userId, ownerKey);
  return null;
}
beforeEach(() => {
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
    context: { product: { selectedProductId: 'p1', selectedShadeId: 's1' }, style: {
      kind: 'catalog', lookId: 'look1', recipeId: 'recipe1', recipeVersion: 'v1', currentStep: 1,
      conditions: [{ slot: 'color', value: 'coral' }], historicalCandidateRefs: [{ kind: 'catalog', lookId: 'look1' }],
    } },
    messages: [{ id: 'm2', role: 'assistant', text: 'answer', displayPayload: { products: [] } }], nextMessageCursor: 10 });
  await act(async () => { expect(await current.open('room')).toBe('room'); });
  let room = useChatConversationStore.getState().conversations.room;
  expect(room.view.linkedProduct).toMatchObject({ productId: 'p1', shadeId: 's1' });
  expect(room.conversation.styleContext).toEqual({ kind: 'catalog', lookId: 'look1', recipeId: 'recipe1',
    recipeVersion: 'v1', currentStep: 1 });
  expect(room.conversation.styleConditions).toEqual([{ slot: 'color', value: 'coral' }]);
  expect(room.messages.map((message) => message.text)).toEqual(['answer']);
  expect(room.conversation.beautyContext?.session).toBeUndefined();
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
