import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { useSkinV2Recommendation } from '@/hooks/useSkinV2Recommendation';
import type { SkinProfile } from '@/types/skin';

const mockQuery = jest.fn((options: { enabled: boolean; queryFn: () => Promise<unknown> }) => options);
const mockPost = jest.fn(async (..._args: unknown[]) => ({ matches: [] }));
const mockUseAuth = jest.fn<{user: {id: string} | null}, []>(() => ({ user: null }));
jest.mock('@/lib/auth', () => ({ useAuth: () => ({ ready: true, ...mockUseAuth() }) }));
jest.mock('@tanstack/react-query', () => ({ useQuery: (options: Parameters<typeof mockQuery>[0]) => mockQuery(options) }));
jest.mock('@/lib/api', () => ({ apiPost: (...args: unknown[]) => mockPost(...args) }));
jest.mock('@/lib/recommendationComparison', () => ({
  comparisonInput: (_profile: unknown, ageGroup: string, gender: string) => ({
    ageGroup, gender, analysisVersion: 'skin-analysis-v4.1', scores: { acne: 0.4 },
  }),
}));

it('requires demographics before the V2 request and sends the analysis input to the public route', async () => {
  const profile = { version: 4, demographics: {}, analysis: {
    schema: 'skin-analysis-mobile-v4.1', acneScore: 0.4, timing: { runId: 'one' },
  } } as SkinProfile;
  let result!: ReturnType<typeof useSkinV2Recommendation>;
  function Probe() { result = useSkinV2Recommendation(profile, true); return null; }
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<Probe />); });
  expect(result.problem).toBe('comparison.needDemographics');
  expect(mockQuery.mock.lastCall?.[0].enabled).toBe(false);
  await act(async () => { result.setAge('30대'); });
  await act(async () => { result.setGender('여성'); });
  expect(mockQuery.mock.lastCall?.[0].enabled).toBe(true);
  await mockQuery.mock.lastCall?.[0].queryFn();
  expect(mockPost).toHaveBeenCalledWith('/api/recommendations/skin-v2',
    expect.objectContaining({ ageGroup: '30대', gender: '여성' }), expect.any(Object));
  await act(async () => { screen.unmount(); });
});

it('asks for a new analysis when the saved result lacks a trouble score', async () => {
  const profile = { version: 4, analysis: { schema: 'skin-analysis-mobile-v4',
    timing: { runId: 'two' } } } as SkinProfile;
  let result!: ReturnType<typeof useSkinV2Recommendation>;
  function Probe() { result = useSkinV2Recommendation(profile, true); return null; }
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<Probe />); });
  expect(result.problem).toBe('comparison.needV41');
  expect(mockQuery.mock.lastCall?.[0].enabled).toBe(false);
  await act(async () => { screen.unmount(); });
});

it('uses the authenticated recorded route and scopes its query to the member', async () => {
  mockUseAuth.mockReturnValueOnce({ user: { id: 'member-a' } });
  const profile = { version: 4, demographics: { age: 32, gender: '여성' }, analysis: {
    schema: 'skin-analysis-mobile-v4.1', acneScore: 0.4, timing: { runId: 'three' },
  } } as SkinProfile;
  function Probe() { useSkinV2Recommendation(profile, true); return null; }
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<Probe />); });
  await mockQuery.mock.lastCall?.[0].queryFn();
  expect(mockPost).toHaveBeenLastCalledWith('/api/recommendations/skin-v2/recorded',
    { sessionId: expect.any(String), input: expect.objectContaining({ ageGroup: '30대' }) },
    expect.objectContaining({ expectedUserId: 'member-a' }));
  await act(async () => { screen.unmount(); });
});
