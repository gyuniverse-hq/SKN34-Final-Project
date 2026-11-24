import { createElement } from 'react';
import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import { useChatMemory } from '@/hooks/useChatMemory';
import { apiChatUserRequest } from '@/lib/api';
import type { ChatMemoryProposal } from '@/types';

jest.mock('@/lib/api', () => ({ apiChatUserRequest: jest.fn() }));

const mockRequest = apiChatUserRequest as jest.MockedFunction<typeof apiChatUserRequest>;
let current: ReturnType<typeof useChatMemory>;
function Harness({ userId }: { userId: string | null }) {
  current = useChatMemory(userId);
  return null;
}

const proposal: ChatMemoryProposal = {
  proposalId: 'proposal-1', version: 1, kind: 'preference', value: '코랄 립',
  consentScope: 'future_consultations', expiresAt: '2026-11-24T12:00:00Z',
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
