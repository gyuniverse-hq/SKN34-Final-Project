import type { BeautyChatContext } from '@/types';
import type { ChatRequestSnapshot, ConversationTarget } from '@/types/chatConversation';
import { useChatConversationStore } from '@/store/chatConversationStore';

const store = useChatConversationStore.getState;

function request(target: ConversationTarget, message = 'question'): ChatRequestSnapshot {
  const room = store().conversations[target.id].conversation;
  return { automatic: false, revision: room.selection.revision, generation: room.generation, styleRevision: room.styleRevision,
    args: { message, category: room.category, locale: 'ko', requestId: 'request-' + (room.serial + 1),
      expectedUserId: room.userId, styleContext: room.styleContext } };
}

beforeEach(() => {
  useChatConversationStore.setState({ identity: undefined, conversations: {}, latest: {} });
  store().activate('account-A');
});

test('keeps namespaced subjects separate and resumes earlier IDs without deleting newer records', () => {
  const general = store().open({ type: 'general' })!;
  const look = store().open({ type: 'look', kind: 'video', lookId: 'same-id' })!;
  const catalog = store().open({ type: 'look', kind: 'catalog', lookId: 'same-id' })!;
  const product = store().open({ type: 'product', productId: 'same-id', shadeId: '03' })!;
  const next = store().open({ type: 'general' }, true)!;
  expect(new Set([general, look, catalog, product, next, 'same-id']).size).toBe(6);
  expect(store().open({ type: 'product', productId: 'same-id', shadeId: '05' })).toBe(product);
  expect(store().conversations[product].view.linkedProduct?.shadeId).toBe('05');
  expect(store().resume(general)).toBe(true);
  expect(store().open({ type: 'general' })).toBe(general);
  expect(store().conversations[next]).toBeDefined();
});

test('clears all rooms, sessions and drafts on owner change and rejects stale updates', () => {
  const id = store().open({ type: 'general' })!;
  const room = store().conversations[id].conversation;
  store().setDraft(room, 'private draft');
  const ticket = store().beginRequest(room, request(room, 'private question'))!;
  store().activate('account-A');
  expect(store().conversations[id].view.draft).toBe('private draft');
  store().activate(null);
  store().completeRequest(ticket, { answer: 'late reply', products: [] }, 'private question');
  expect(store().resume(id)).toBe(false);
  expect(store().conversations).toEqual({});
  store().activate('account-A');
  expect(store().open({ type: 'general' })).not.toBe(id);
});

test('a fresh app store has no saved chat or pending request to restore', () => {
  const id = store().open({ type: 'general' })!;
  const room = store().conversations[id].conversation;
  store().beginRequest(room, request(room, 'memory-only transcript'));

  jest.isolateModules(() => {
    const { useChatConversationStore: freshStore } =
      jest.requireActual<typeof import('@/store/chatConversationStore')>('@/store/chatConversationStore');
    expect(freshStore.getState().identity).toBeUndefined();
    expect(freshStore.getState().conversations).toEqual({});
    expect(freshStore.getState().resume(id)).toBe(false);
  });
  expect(store().conversations[id].view.pending).toBe(true);
});

test('notifies subscribers atomically without mutating previous records or retry snapshots', () => {
  const id = store().open({ type: 'general' })!;
  const target = store().conversations[id].conversation;
  const before = store().conversations[id];
  Object.freeze(before.conversation);
  Object.freeze(before.messages);
  Object.freeze(before.conversation.selection);
  Object.freeze(before.conversation.selection.shades);
  Object.freeze(before.conversation.selection.changed);
  const changed = jest.fn();
  const unsubscribe = useChatConversationStore.subscribe(changed);
  store().setDraft(target, 'question');
  store().setCategory(target, 'ingredient');
  expect(changed).toHaveBeenCalledTimes(2);
  expect(before.view.draft).toBe('');
  expect(before.conversation.category).toBe('product');
  const ready = store().conversations[id];
  const snapshot = request(target);
  const ticket = store().beginRequest(target, snapshot)!;
  expect(changed).toHaveBeenCalledTimes(3);
  expect(ready.messages).toEqual([]);
  expect(ready.conversation.snapshots.size).toBe(0);
  const pending = store().conversations[id];
  store().failRequest(ticket, 'chat.ui.error', false, false);
  expect(changed).toHaveBeenCalledTimes(4);
  expect(pending.view.pending).toBe(true);
  expect(pending.messages[0].failed).toBeUndefined();
  expect(store().conversations[id].messages[0].retryable).toBe(true);
  const retry = store().beginRequest(target, snapshot, ticket.messageId)!;
  expect(retry.requestId).toBe(ticket.requestId);
  expect(retry.attempt).not.toBe(ticket.attempt);
  const retrying = store().conversations[id];
  store().completeRequest(ticket, { answer: 'stale attempt', products: [] }, 'question');
  store().failRequest(ticket, 'chat.ui.error', false, false);
  expect(store().conversations[id]).toBe(retrying);
  store().completeRequest(retry, { answer: 'answer', products: [] }, 'question');
  expect(changed).toHaveBeenCalledTimes(6);
  expect(retrying.conversation.snapshots.get(ticket.messageId)).toBe(snapshot);
  expect(retrying.messages).toHaveLength(1);
  expect(store().conversations[id].messages.map((message) => message.text)).toEqual(['question', 'answer']);
  expect(store().conversations[id].view.pending).toBe(false);
  unsubscribe();
});

test('isolates concurrent requests and validates ownership across logout and same-account login', () => {
  const a = store().open({ type: 'product', productId: 'a', shadeId: 'a-1' })!;
  const b = store().open({ type: 'look', kind: 'video', lookId: 'b' })!;
  const targetA = store().conversations[a].conversation;
  const targetB = store().conversations[b].conversation;
  const oldB = store().conversations[b];
  store().setDraft(targetA, 'unsent');
  store().setCategory(targetA, 'ingredient');
  expect(store().conversations[b]).toBe(oldB);
  const ta = store().beginRequest(targetA, request(targetA))!;
  const tb = store().beginRequest(targetB, request(targetB))!;
  expect(ta).toBeDefined();
  expect(tb).toBeDefined();
  expect(store().beginRequest(targetA, request(targetA))).toBeUndefined();
  store().resume(b);
  store().completeRequest(ta, { answer: 'only A', products: [] }, 'question');
  expect(store().conversations[b].view.pending).toBe(true);
  expect(store().conversations[b].messages).toHaveLength(1);
  expect(store().conversations[a].messages.at(-1)?.text).toBe('only A');
  store().resume(a);
  expect(store().conversations[a].view).toMatchObject({ draft: 'unsent', category: 'ingredient', linkedProduct: { shadeId: 'a-1' } });
  const before = store();
  const wrongOwner = { id: a, ownerKey: 'not-the-owner' };
  store().setDraft(wrongOwner, 'corruption');
  store().setCategory(wrongOwner, 'style');
  store().resetSession(wrongOwner, 'chat.session.expired');
  expect(store()).toBe(before);
  store().activate(null);
  store().activate('account-A');
  const replacement = store().open({ type: 'look', kind: 'video', lookId: 'b' })!;
  store().completeRequest(tb, { answer: 'old account reply', products: [] }, 'question');
  store().failRequest(tb, 'chat.ui.error', false, false);
  expect(store().conversations[replacement].messages).toEqual([]);
});

test('session reset rejects old completion and keeps its earlier snapshot immutable', () => {
  const id = store().open({ type: 'general' })!;
  const target = store().conversations[id].conversation;
  const ticket = store().beginRequest(target, request(target))!;
  const before = store().conversations[id];
  store().resetSession(target, 'chat.session.expired');
  expect(before.conversation.generation).toBe(0);
  expect(before.conversation.snapshots.size).toBe(1);
  expect(before.view.pending).toBe(true);
  const reset = store().conversations[id];
  store().completeRequest(ticket, { answer: 'expired', products: [] }, 'question');
  expect(store().conversations[id]).toBe(reset);
  expect(reset.conversation.snapshots.size).toBe(0);
  expect(reset.view.pending).toBe(false);
});

test('selection, shades and server session reconcile immutably while another request is in flight', () => {
  const id = store().open({ type: 'general' })!;
  const target = store().conversations[id].conversation;
  const context: BeautyChatContext = {
    version: 1, issuedAt: 1000, candidateIds: ['a', 'b'], scopeIds: ['a', 'b'], selectedProductId: null,
    filters: { category: 'lip', maxPriceKRW: 20000, fragranceFree: false, moisturizing: true, query: '' },
    session: { sessionId: 'session', sessionToken: 'test-capability', resultSetId: 'results',
      stateVersion: 1, expiresAt: Math.floor(Date.now() / 1000) + 300 },
  };
  const ticket = store().beginRequest(target, request(target))!;
  store().completeRequest(ticket, { answer: 'products', products: [], chatContext: context }, 'question');
  const answer = store().conversations[id].messages[1];
  const beforeSelection = store().conversations[id];
  Object.freeze(beforeSelection.conversation.beautyContext);
  Object.freeze(beforeSelection.conversation.selection.shades);
  store().selectProduct(target, 'b', answer);
  const selected = store().conversations[id];
  expect(beforeSelection.view.chosenProductId).toBeNull();
  expect(selected.view.chosenProductId).toBe('b');
  expect(selected.conversation.beautyContext?.session).toEqual(context.session);
  const next = store().beginRequest(target, request(target, 'details'))!;
  const pending = store().conversations[id];
  store().selectShade(target, 'b', 'b-2', answer);
  expect(pending.conversation.selection.shades).toEqual({});
  store().completeRequest(next, { answer: 'details', products: [], chatContext: {
    ...context, shadeSelections: { b: 'b-1' }, session: { ...context.session!, stateVersion: 2 },
  } }, 'details');
  const current = store().conversations[id];
  expect(current.view.chosenProductId).toBe('b');
  expect(current.view.selectedShades).toEqual({ b: 'b-2' });
  expect(current.conversation.beautyContext?.candidateIds).toEqual(['a', 'b']);
  expect(current.conversation.beautyContext?.session?.stateVersion).toBe(2);
  expect(pending.conversation.beautyContext?.session?.stateVersion).toBe(1);
  expect(beforeSelection.messages[1].chatContext?.session).toBeUndefined();
});
