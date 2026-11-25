import { createElement, useLayoutEffect } from 'react';
import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import { MemoryProposalGroup } from '@/components/chat/MemoryProposalGroup';
import { useChatMemory } from '@/hooks/useChatMemory';
import { apiChatUserRequest } from '@/lib/api';
import type { ChatMemoryDecision, ChatMemoryProposal, ChatMemoryProposalGroup } from '@/types';

jest.mock('@/lib/api', () => ({ apiChatUserRequest: jest.fn(), ApiError: class extends Error {} }));
jest.mock('@/lib/i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }));

const mockRequest = apiChatUserRequest as jest.MockedFunction<typeof apiChatUserRequest>;
let current: ReturnType<typeof useChatMemory>;
function Harness({ userId }: { userId: string | null }) {
  const memory = useChatMemory(userId);
  useLayoutEffect(() => { current = memory; }, [memory]);
  return null;
}

const proposal: ChatMemoryProposal = {
  proposalId: 'proposal-1', version: 1, kind: 'preference', value: '코랄 립',
  consentScope: 'future_consultations', expiresAt: '2026-11-24T12:00:00Z',
};

const group: ChatMemoryProposalGroup = {
  groupId: 'group-1', conversationId: 'room-1', expiresAt: '2099-01-01T00:00:00Z',
  items: [
    { itemId: 'skin', key: 'skin.type', kind: 'profile', version: 1, status: 'pending',
      displayValue: '건성', editableValue: 'dry', value: { type: 'dry' }, choices: [['dry', '건성']] },
    { itemId: 'color', key: 'makeup.color', kind: 'preference', version: 2, status: 'pending',
      displayValue: '코랄 립', editableValue: 'coral', value: { family: 'coral', area: 'lip' }, choices: [['coral', '코랄']] },
  ],
};

beforeEach(() => mockRequest.mockReset());

it('confirms the exact server proposal and retries with the same request ID', async () => {
  let view!: ReactTestRenderer;
  await act(async () => { view = create(createElement(Harness, { userId: 'A' })); });
  mockRequest.mockRejectedValueOnce(new Error('lost response'));
  await act(async () => { await expect(current.confirm(proposal)).rejects.toThrow(); });
  const first = mockRequest.mock.calls[0][3] as { requestId: string; proposalId: string; confirmed: boolean };
  expect(first.proposalId).toBe(proposal.proposalId);
  expect(first.confirmed).toBe(true);
  mockRequest.mockResolvedValueOnce({ memoryId: 'memory-1', memoryVersion: 1 });
  await act(async () => { await current.confirm(proposal); });
  const retry = mockRequest.mock.calls[1][3] as { requestId: string };
  expect(retry.requestId).toBe(first.requestId);
  expect(current.memories[0].value).toBe('코랄 립');
  await act(async () => view.unmount());
});

it('does not expose a late response after switching accounts', async () => {
  let view!: ReactTestRenderer;
  let finish!: (value: unknown) => void;
  mockRequest.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  await act(async () => { view = create(createElement(Harness, { userId: 'A' })); });
  let pending!: Promise<unknown>;
  await act(async () => { pending = current.refresh(); });
  await act(async () => { view.update(createElement(Harness, { userId: 'B' })); });
  await act(async () => { finish({ memories: [{ id: 'a', value: 'private A' }] }); await pending; });
  expect(current.memories).toEqual([]);
  await act(async () => view.unmount());
});

it('sends one decision per visible item and uses the same ID after a lost response', async () => {
  let view!: ReactTestRenderer;
  await act(async () => { view = create(createElement(Harness, { userId: 'A' })); });
  mockRequest.mockResolvedValueOnce([group]);
  await act(async () => { await current.refreshProposals(group.conversationId); });
  const decisions: ChatMemoryDecision[] = [
    { itemId: 'skin', expectedVersion: 1, action: 'approve', confirmed: true },
    { itemId: 'color', expectedVersion: 2, action: 'defer' },
  ];
  mockRequest.mockRejectedValueOnce(new Error('lost response'));
  await act(async () => { await expect(current.decideProposals(group, decisions)).rejects.toThrow(); });
  expect(current.proposalState?.groups[0].items).toHaveLength(2);
  mockRequest.mockResolvedValueOnce({ items: [
    { itemId: 'skin', status: 'approved' }, { itemId: 'color', status: 'deferred' },
  ] });
  await act(async () => { await current.decideProposals(group, decisions); });
  expect(mockRequest.mock.calls[1][3]).toEqual(mockRequest.mock.calls[2][3]);
  expect(current.proposalState?.groups[0].items).toEqual([{ ...group.items[1], status: 'deferred' }]);
  await act(async () => view.unmount());
});

it('ignores an old decision even after returning to the same account', async () => {
  let view!: ReactTestRenderer;
  let finish!: (value: unknown) => void;
  await act(async () => { view = create(createElement(Harness, { userId: 'A' })); });
  mockRequest.mockResolvedValueOnce([group]);
  await act(async () => { await current.refreshProposals(group.conversationId); });
  mockRequest.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  let pending!: Promise<unknown>;
  await act(async () => {
    pending = current.decideProposals(group, [{ itemId: 'skin', expectedVersion: 1, action: 'defer' }])
      .catch((error: unknown) => error);
  });
  expect(current.busy).toBe(true);
  await act(async () => { view.update(createElement(Harness, { userId: 'B' })); });
  await act(async () => { view.update(createElement(Harness, { userId: 'A' })); });
  expect(current.busy).toBe(false);
  expect(current.proposalState).toBeUndefined();
  await act(async () => {
    finish({ items: [{ itemId: 'skin', status: 'deferred' }] });
    await expect(pending).resolves.toEqual(new Error('Chat owner changed'));
  });
  expect(current.proposalState).toBeUndefined();
  await act(async () => view.unmount());
});

it('starts with every item unselected and only approves the item the user selects', async () => {
  const onDecide = jest.fn(async () => true);
  let view!: ReactTestRenderer;
  const currentGroup = { ...group, expiresAt: new Date(Date.now() + 60_000).toISOString() };
  await act(async () => {
    view = create(createElement(MemoryProposalGroup, { group: currentGroup, busy: false, onEdit: async () => true, onDecide }));
  });
  const boxes = group.items.map((item) => view.root.findAll((node) =>
    node.props.accessibilityRole === 'checkbox' && node.props.accessibilityLabel === item.displayValue
    && typeof node.props.onPress === 'function')[0]);
  expect(boxes.map((node) => node?.props.accessibilityState.checked)).toEqual([false, false]);
  expect(boxes.map((node) => node?.props['aria-checked'])).toEqual([false, false]);
  await act(async () => { boxes[0].props.onPress(); });
  expect(boxes[0].props['aria-checked']).toBe(true);
  let apply = view.root.findAll((node) => node.props.children === 'chat.memory.applyDecisions')[0]?.parent;
  while (apply && typeof apply.props.onPress !== 'function') apply = apply.parent;
  expect(apply?.props.disabled).toBe(false);
  await act(async () => { await apply?.props.onPress(); });
  expect(onDecide).toHaveBeenCalledWith([
    { itemId: 'skin', expectedVersion: 1, action: 'approve', confirmed: true },
    { itemId: 'color', expectedVersion: 2, action: 'defer' },
  ]);
  await act(async () => view.unmount());
});
