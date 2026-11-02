import { createElement } from 'react';
import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import { useChat } from '@/hooks/useChat';
import { apiPost } from '@/lib/api';
import type { BeautyChatContext } from '@/types';

let mockMutation: (input: unknown) => Promise<unknown>;
jest.mock('@tanstack/react-query', () => ({
  useMutation: (options: { mutationFn: typeof mockMutation }) => {
    mockMutation = options.mutationFn;
    return {};
  },
}));
jest.mock('@/lib/api', () => ({ apiPost: jest.fn(), CHAT_API_BASE_URL: 'http://chat.test' }));
jest.mock('@/lib/chatIdentity', () => ({ getAnonymousChatId: async () => 'guest-session-test' }));

function Harness() { useChat(); return null; }

const context: BeautyChatContext = {
  version: 1, issuedAt: 1000, candidateIds: ['p1', 'p2'], scopeIds: ['p1', 'p2'],
  selectedProductId: null,
  filters: { category: 'lip', maxPriceKRW: 20000, fragranceFree: false, moisturizing: true, query: '' },
};

it.each([undefined, 'style'])('preserves legacy chat transport for category %s', async (category) => {
  let view!: ReactTestRenderer;
  await act(async () => { view = create(createElement(Harness)); });
  await mockMutation({ message: 'question', locale: 'ko', category, chatContext: context });
  expect(apiPost).toHaveBeenLastCalledWith('/api/chat', { message: 'question', locale: 'ko' },
    expect.objectContaining({ baseUrl: 'http://chat.test', timeoutMs: 90_000 }));
  await act(async () => { view.unmount(); });
});

it.each(['product', 'ingredient'])('passes structured context only to the explicit beauty route: %s', async (category) => {
  let view!: ReactTestRenderer;
  await act(async () => { view = create(createElement(Harness)); });
  await mockMutation({ message: '두 번째 제품', locale: 'ko', category, chatContext: context });
  expect(apiPost).toHaveBeenLastCalledWith('/api/chat', {
    message: '두 번째 제품', locale: 'ko', requestType: 'beauty_consultation', chatContext: context,
  }, expect.objectContaining({ headers: { 'X-Vishue-Anonymous-Id': 'guest-session-test' } }));
  await act(async () => { view.unmount(); });
});
