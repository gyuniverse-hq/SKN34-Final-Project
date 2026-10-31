import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createElement, useEffect } from 'react';
import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import { apiPost } from '@/lib/api';
import { useSkinRecommendations } from '@/lib/queries';
import type { SkinRecommendationRequest, SkinRecommendationResponse } from '@/types';

jest.mock('@/lib/api', () => ({ apiGet: jest.fn(), apiPost: jest.fn() }));

const response: SkinRecommendationResponse = {
  strategyVersion: 'skin-concern-v1', concerns: ['dryness'], status: 'empty_catalog', matches: [],
};

let client: QueryClient;
let tree: ReactTestRenderer | undefined;
let query: ReturnType<typeof useSkinRecommendations>;

function Probe({ request }: { request?: SkinRecommendationRequest }) {
  const result = useSkinRecommendations(request);
  useEffect(() => { query = result; }, [result]);
  return null;
}

function render(request?: SkinRecommendationRequest) {
  return createElement(QueryClientProvider, { client }, createElement(Probe, { request }));
}

beforeEach(() => {
  jest.useFakeTimers();
  jest.mocked(apiPost).mockReset().mockResolvedValue(response);
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
});

afterEach(async () => {
  await act(async () => { tree?.unmount(); });
  tree = undefined;
  client.clear();
  jest.useRealTimers();
});

it('waits for a confirmed request and preserves the empty-catalog response', async () => {
  await act(async () => { tree = create(render()); });
  expect(apiPost).not.toHaveBeenCalled();

  const request: SkinRecommendationRequest = { concerns: ['dryness'], limit: 8 };
  await act(async () => { tree!.update(render(request)); });
  await act(async () => { await jest.advanceTimersByTimeAsync(10); });
  expect(apiPost).toHaveBeenCalledWith('/api/recommendations/skin', request);
  expect(query.data).toEqual(response);
});

it('hides old results while concerns are edited and fetches the newly confirmed selection', async () => {
  await act(async () => { tree = create(render({ concerns: ['dryness'], limit: 8 })); });
  await act(async () => { await jest.advanceTimersByTimeAsync(10); });
  expect(query.data?.concerns).toEqual(['dryness']);

  await act(async () => { tree!.update(render()); });
  expect(query.data).toBeUndefined();
  expect(apiPost).toHaveBeenCalledTimes(1);

  jest.mocked(apiPost).mockResolvedValue({ ...response, concerns: ['pores'], status: 'no_matches' });
  const request: SkinRecommendationRequest = { concerns: ['pores'], limit: 8 };
  await act(async () => { tree!.update(render(request)); });
  await act(async () => { await jest.advanceTimersByTimeAsync(10); });
  expect(apiPost).toHaveBeenLastCalledWith('/api/recommendations/skin', request);
  expect(query.data?.status).toBe('no_matches');
  expect(query.data?.concerns).toEqual(['pores']);
});

it('exposes request failures instead of replacing them with an empty success', async () => {
  jest.mocked(apiPost).mockRejectedValue(new Error('network failure'));
  await act(async () => { tree = create(render({ concerns: ['dryness'], limit: 8 })); });
  await act(async () => { await jest.advanceTimersByTimeAsync(10); });
  expect(query.isError).toBe(true);
  expect(query.error?.message).toBe('network failure');
  expect(query.data).toBeUndefined();
});
