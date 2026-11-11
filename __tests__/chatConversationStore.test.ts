import { useChatConversationStore } from '@/store/chatConversationStore';

const store = useChatConversationStore.getState;

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
  room.draft.current = 'private draft';
  room.request.current = 'old-in-flight-request';
  store().update(room, () => [{ id: '1', role: 'user', text: 'private question' }]);
  store().activate('account-A');
  expect(store().conversations[id].view.draft).toBe('private draft');
  store().activate(null);
  store().update(room, () => [{ id: '2', role: 'assistant', text: 'late reply' }]);
  expect(store().resume(id)).toBe(false);
  expect(store().conversations).toEqual({});
  store().activate('account-A');
  expect(store().open({ type: 'general' })).not.toBe(id);
});

test('a fresh app store has no saved chat or pending request to restore', () => {
  const id = store().open({ type: 'general' })!;
  const room = store().conversations[id].conversation;
  room.request.current = 'memory-only-request';
  store().update(room, () => [{ id: '1', role: 'user', text: 'memory-only transcript' }]);

  jest.isolateModules(() => {
    const { useChatConversationStore: freshStore } =
      jest.requireActual<typeof import('@/store/chatConversationStore')>('@/store/chatConversationStore');
    expect(freshStore.getState().identity).toBeUndefined();
    expect(freshStore.getState().conversations).toEqual({});
    expect(freshStore.getState().resume(id)).toBe(false);
  });
  expect(store().conversations[id].view.pending).toBe(true);
});
