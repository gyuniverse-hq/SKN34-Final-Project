import { createElement, useEffect } from 'react';
import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import { useSkinReport } from '@/hooks/useSkinReport';
import { useSkincareRecommendations } from '@/lib/queries';
import { SKIN_REPORT_EXAMPLE } from '@/constants/skinCare';
import type { SkinProfile } from '@/types/skin';

let mockProfile: SkinProfile | null = null;
const mockHydrate = jest.fn<Promise<void>, []>();
jest.mock('@/store/skinProfileStore', () => ({
  useSkinProfileStore: (selector: (state: { profile: SkinProfile | null; hydrate: () => Promise<void> }) => unknown) =>
    selector({ profile: mockProfile, hydrate: mockHydrate }),
}));
jest.mock('@/lib/queries', () => ({ useSkincareRecommendations: jest.fn(() => ({ refetch: jest.fn() })) }));

let flow: ReturnType<typeof useSkinReport>;
let tree: ReactTestRenderer | undefined;
function Probe() {
  const result = useSkinReport();
  useEffect(() => { flow = result; }, [result]);
  return null;
}
beforeEach(() => {
  mockProfile = null;
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
  expect(flow.selected).toEqual([]);
  expect(flow.primary).toBeUndefined();
  expect(useSkincareRecommendations).toHaveBeenLastCalledWith(undefined);
});

it('preserves a storage failure for the screen error state rather than hiding it behind sample success', async () => {
  mockHydrate.mockRejectedValue(new Error('storage unavailable'));
  await act(async () => { tree = create(createElement(Probe)); });
  expect(flow.loadFailed).toBe(true);
  expect(flow.loading).toBe(false);
  expect(useSkincareRecommendations).toHaveBeenLastCalledWith(undefined);
});

it('automatically requests products after hydration and updates when goals change', async () => {
  mockProfile = { ...SKIN_REPORT_EXAMPLE, analysis: { ...SKIN_REPORT_EXAMPLE.analysis, timing: { runId: 'test' } } } as SkinProfile;
  await act(async () => { tree = create(createElement(Probe)); });
  expect(flow.live).toBe(true);
  expect(useSkincareRecommendations).toHaveBeenLastCalledWith(expect.objectContaining({ primaryGoal: 'dryness' }));
  await act(async () => { flow.setPrimary('dryness'); flow.toggle('pores'); });
  expect(useSkincareRecommendations).toHaveBeenLastCalledWith(expect.objectContaining({
    primaryGoal: 'dryness', secondaryGoals: ['pores'],
  }));
  expect(useSkincareRecommendations).toHaveBeenLastCalledWith(expect.not.objectContaining({ questionnaire: expect.anything() }));
  await act(async () => { flow.toggle('pores'); });
  expect(flow.selected).toEqual([]);
  expect(flow.live).toBe(true);
  expect(useSkincareRecommendations).toHaveBeenLastCalledWith(expect.objectContaining({ secondaryGoals: [] }));
});

it('allows a successful retry after a storage error', async () => {
  mockHydrate.mockRejectedValueOnce(new Error('storage unavailable'));
  await act(async () => { tree = create(createElement(Probe)); });
  expect(flow.loadFailed).toBe(true);
  await act(async () => { await flow.reload(); });
  expect(flow.loadFailed).toBe(false);
  expect(flow.loading).toBe(false);
});
