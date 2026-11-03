import { createElement } from 'react';
import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import { useChat } from '@/hooks/useChat';
import { apiPostChat } from '@/lib/api';
import type { BeautyChatContext } from '@/types';

let mockMutation: (input: unknown) => Promise<unknown>;
jest.mock('@tanstack/react-query', () => ({
  useMutation: (options: { mutationFn: typeof mockMutation }) => {
    mockMutation = options.mutationFn;
    return {};
  },
}));
jest.mock('@/lib/api', () => ({ apiPostChat: jest.fn() }));
jest.mock('@/lib/chatIdentity', () => ({ getAnonymousChatId: async () => 'guest-session-test' }));

function Harness() { useChat(); return null; }

it('sends Style progress independently from product sessions and preserves the retry UUID', async () => {
  let view!: ReactTestRenderer;
  await act(async () => { view = create(createElement(Harness)); });
  const styleContext = { kind: 'video', lookId: '_video-1', recipeId: 'video:_video-1', recipeVersion: 'v1', currentStep: 1 };
  const args = { message: '다음 단계', locale: 'ko', category: 'style', styleContext, chatContext: context,
    requestId: '20000000-0000-4000-8000-000000000001' };
  await mockMutation(args);
  await mockMutation(args);
  expect(apiPostChat).toHaveBeenLastCalledWith({ message: args.message, locale: 'ko', requestType: 'style_consultation',
    styleContext, requestId: args.requestId }, expect.anything());
  await act(async () => view.unmount());
});

const context: BeautyChatContext = {
  version: 1, issuedAt: 1000, candidateIds: ['p1', 'p2'], scopeIds: ['p1', 'p2'],
  selectedProductId: null,
  filters: { category: 'lip', maxPriceKRW: 20000, fragranceFree: false, moisturizing: true, query: '' },
};

it.each([undefined])('preserves legacy chat transport for category %s', async (category) => {
  let view!: ReactTestRenderer;
  await act(async () => { view = create(createElement(Harness)); });
  await mockMutation({ message: 'question', locale: 'ko', category, chatContext: context });
  expect(apiPostChat).toHaveBeenLastCalledWith({ message: 'question', locale: 'ko', requestId: expect.stringMatching(/^[0-9a-f-]{36}$/i) },
    expect.objectContaining({ timeoutMs: 90_000 }));
  await act(async () => { view.unmount(); });
});

it.each(['product', 'ingredient'])('passes structured context only to the explicit beauty route: %s', async (category) => {
  let view!: ReactTestRenderer;
  await act(async () => { view = create(createElement(Harness)); });
  await mockMutation({ message: '두 번째 제품', locale: 'ko', category, chatContext: context });
  expect(apiPostChat).toHaveBeenLastCalledWith({
    message: '두 번째 제품', locale: 'ko', requestType: 'beauty_consultation', chatContext: context,
    requestId: expect.stringMatching(/^[0-9a-f-]{36}$/i),
  }, expect.objectContaining({ timeoutMs: 90_000 }));
  await act(async () => { view.unmount(); });
});

it('passes exact shade selections and screen references without synthesizing a shade', async () => {
  let view!: ReactTestRenderer;
  await act(async () => { view = create(createElement(Harness)); });
  const selected = { ...context, shadeSelections: { p2: 'p2-03' } };
  const screenContext = { screenId: 'chat', productId: 'p2', shadeId: 'p2-03' };
  await mockMutation({ message: '03호 성분', locale: 'ja', category: 'ingredient',
    chatContext: selected, screenContext });
  expect(apiPostChat).toHaveBeenLastCalledWith(expect.objectContaining({
    chatContext: selected, screenContext, requestType: 'beauty_consultation', locale: 'ja',
  }), expect.anything());
  await act(async () => { view.unmount(); });
});
