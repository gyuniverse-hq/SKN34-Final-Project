import { createElement, useEffect } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import { useSkinReport } from '@/hooks/useSkinReport';
import { SKIN_REPORT_EXAMPLE } from '@/constants/skinCare';
import { apiPost } from '@/lib/api';
import type { SkinProfile } from '@/types/skin';

let mockProfile: SkinProfile | null = null;
let mockOwner: string | undefined;
const mockHydrate = jest.fn<Promise<void>, []>();
jest.mock('@/store/skinProfileStore', () => ({
  useSkinProfileStore: (selector: (state: { owner: string | null; profile: SkinProfile | null; hydrate: () => Promise<void> }) => unknown) =>
    selector({ owner: mockOwner ?? null, profile: mockProfile, hydrate: mockHydrate }),
}));
jest.mock('@/lib/api', () => ({ apiPost: jest.fn().mockResolvedValue({ overallTop5: [] }) }));
jest.mock('@/lib/auth', () => ({ useAuth: () => ({ user: mockOwner && { id: mockOwner }, ready: true }) }));

let flow: ReturnType<typeof useSkinReport>;
let tree: ReactTestRenderer | undefined;
function Probe() {
  const result = useSkinReport();
  useEffect(() => { flow = result; }, [result]);
  return null;
}

async function mountReport() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    tree = create(createElement(QueryClientProvider, { client }, createElement(Probe)));
  });
}

beforeEach(() => {
  mockProfile = null;
  mockOwner = undefined;
  jest.clearAllMocks();
  mockHydrate.mockResolvedValue(undefined);
});
afterEach(async () => { await act(async () => { tree?.unmount(); }); });

it('shows an explicit example only after storage loads and does not request live products', async () => {
  await mountReport();
  expect(flow.loading).toBe(false);
  expect(flow.loadFailed).toBe(false);
  expect(flow.example).toBe(true);
  expect(flow.live).toBe(false);
  expect(apiPost).not.toHaveBeenCalled();
});

it('preserves a storage failure for the screen error state rather than hiding it behind sample success', async () => {
  mockHydrate.mockRejectedValue(new Error('storage unavailable'));
  await mountReport();
  expect(flow.loadFailed).toBe(true);
  expect(flow.loading).toBe(false);
  expect(apiPost).not.toHaveBeenCalled();
});

it('requests rule-based products from a stored profile without demographics or a trouble score', async () => {
  mockProfile = {
    ...SKIN_REPORT_EXAMPLE, version: 1,
    analysis: { ...SKIN_REPORT_EXAMPLE.analysis, timing: { runId: 'test' } },
  } as SkinProfile;
  await mountReport();
  expect(flow.live).toBe(true);
  expect(apiPost).toHaveBeenCalledTimes(1);
  expect(apiPost).toHaveBeenCalledWith('/api/recommendations/skincare/v4', {
    skinType: 'dry',
    irritationSignal: 'unknown',
    detectedConcerns: [{ goal: 'dryness', sources: ['survey'] }],
  });
});

it('allows a successful retry after a storage error', async () => {
  mockHydrate.mockRejectedValueOnce(new Error('storage unavailable'));
  await mountReport();
  expect(flow.loadFailed).toBe(true);
  await act(async () => { await flow.reload(); });
  expect(flow.loadFailed).toBe(false);
  expect(flow.loading).toBe(false);
});

it('scopes signed-in V1 recommendation history to the report session and account', async () => {
  mockOwner = 'owner';
  mockProfile = {
    ...SKIN_REPORT_EXAMPLE, version: 1,
    analysis: { ...SKIN_REPORT_EXAMPLE.analysis, timing: { runId: 'signed-in-report' } },
  } as SkinProfile;
  await mountReport();
  expect(apiPost).toHaveBeenCalledTimes(1);
  expect(apiPost).toHaveBeenCalledWith('/api/recommendations/skincare/v4/recorded', {
    sessionId: expect.any(String), input: expect.objectContaining({ skinType: 'dry' }),
  }, { expectedUserId: 'owner' });
});
