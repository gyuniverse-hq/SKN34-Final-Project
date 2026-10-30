import { createElement, useEffect } from 'react';
import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import { useSkinReport } from '@/hooks/useSkinReport';
import { useSkinRecommendations } from '@/lib/queries';

const mockHydrate = jest.fn<Promise<void>, []>();
jest.mock('@/store/skinProfileStore', () => ({
  useSkinProfileStore: (selector: (state: { profile: null; hydrate: () => Promise<void> }) => unknown) =>
    selector({ profile: null, hydrate: mockHydrate }),
}));
jest.mock('@/lib/queries', () => ({ useSkinRecommendations: jest.fn(() => ({ refetch: jest.fn() })) }));

let flow: ReturnType<typeof useSkinReport>;
let tree: ReactTestRenderer | undefined;
function Probe() {
  const result = useSkinReport();
  useEffect(() => { flow = result; }, [result]);
  return null;
}
beforeEach(() => {
  jest.clearAllMocks();
  mockHydrate.mockResolvedValue(undefined);
});
afterEach(async () => { await act(async () => { tree?.unmount(); }); });

it('shows an explicit example only after storage loads and does not request live products', async () => {
  await act(async () => { tree = create(createElement(Probe)); });
  expect(flow.loading).toBe(false);
  expect(flow.loadFailed).toBe(false);
  expect(flow.example).toBe(true);
  expect(flow.live).toBe(false);
  expect(flow.selected).toEqual(['dryness']); // Example pores are grade 3 (fair), not caution.
  expect(useSkinRecommendations).toHaveBeenLastCalledWith(undefined);
});

it('preserves a storage failure for the screen error state rather than hiding it behind sample success', async () => {
  mockHydrate.mockRejectedValue(new Error('storage unavailable'));
  await act(async () => { tree = create(createElement(Probe)); });
  expect(flow.loadFailed).toBe(true);
  expect(flow.loading).toBe(false);
  expect(useSkinRecommendations).toHaveBeenLastCalledWith(undefined);
});

it('requests confirmed concern codes only and clears the request when concerns are edited', async () => {
  await act(async () => { tree = create(createElement(Probe)); });
  await act(async () => { flow.findProducts(); });
  expect(flow.live).toBe(true);
  expect(useSkinRecommendations).toHaveBeenLastCalledWith({ concerns: ['dryness'], limit: 8 });
  await act(async () => { flow.toggle('dryness'); });
  expect(flow.selected).toEqual([]);
  expect(flow.live).toBe(false);
  expect(useSkinRecommendations).toHaveBeenLastCalledWith(undefined);
});

it('allows a successful retry after a storage error', async () => {
  mockHydrate.mockRejectedValueOnce(new Error('storage unavailable'));
  await act(async () => { tree = create(createElement(Probe)); });
  expect(flow.loadFailed).toBe(true);
  await act(async () => { await flow.reload(); });
  expect(flow.loadFailed).toBe(false);
  expect(flow.loading).toBe(false);
});
