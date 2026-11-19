import { createElement, useEffect } from 'react';
import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import { useSkinReport } from '@/hooks/useSkinReport';
import { useSkinV2Recommendation } from '@/hooks/useSkinV2Recommendation';
import { SKIN_REPORT_EXAMPLE } from '@/constants/skinCare';
import type { SkinProfile } from '@/types/skin';

jest.mock('@/lib/auth', () => ({ useAuth: () => ({ ready: true, user: null }) }));
let mockProfile: SkinProfile | null = null;
const mockHydrate = jest.fn<Promise<void>, []>();
jest.mock('@/store/skinProfileStore', () => ({
  useSkinProfileStore: (selector: (state: { owner: null; profile: SkinProfile | null; hydrate: () => Promise<void> }) => unknown) =>
    selector({ owner: null, profile: mockProfile, hydrate: mockHydrate }),
}));
jest.mock('@/hooks/useSkinV2Recommendation', () => ({ useSkinV2Recommendation: jest.fn(() => ({ query: { refetch: jest.fn() } })) }));

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
  expect(useSkinV2Recommendation).toHaveBeenLastCalledWith(null, true);
});

it('preserves a storage failure for the screen error state rather than hiding it behind sample success', async () => {
  mockHydrate.mockRejectedValue(new Error('storage unavailable'));
  await act(async () => { tree = create(createElement(Probe)); });
  expect(flow.loadFailed).toBe(true);
  expect(flow.loading).toBe(false);
  expect(useSkinV2Recommendation).toHaveBeenLastCalledWith(null, true);
});

it('passes the stored profile to the V2 recommendation hook', async () => {
  mockProfile = { ...SKIN_REPORT_EXAMPLE, analysis: { ...SKIN_REPORT_EXAMPLE.analysis, timing: { runId: 'test' } } } as SkinProfile;
  await act(async () => { tree = create(createElement(Probe)); });
  expect(flow.live).toBe(true);
  expect(useSkinV2Recommendation).toHaveBeenLastCalledWith(mockProfile, true);
});

it('allows a successful retry after a storage error', async () => {
  mockHydrate.mockRejectedValueOnce(new Error('storage unavailable'));
  await act(async () => { tree = create(createElement(Probe)); });
  expect(flow.loadFailed).toBe(true);
  await act(async () => { await flow.reload(); });
  expect(flow.loadFailed).toBe(false);
  expect(flow.loading).toBe(false);
});
