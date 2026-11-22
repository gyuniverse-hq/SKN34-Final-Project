import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { uuid } from 'expo';
import { apiPost } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { comparisonInput } from '@/lib/recommendationComparison';
import type { ComparisonAge, ComparisonGender, ComparisonGoal, RecommendationComparisonInput } from '@/types/recommendationComparison';
import type { Product } from '@/types';
import type { SkinProfile } from '@/types/skin';

export interface SkinV2Result {
  targetConcern: ComparisonGoal;
  matches: { product: Product; optionId: string; optionName: string; priceKRW: number; candidateId?: string }[];
  history?: { requestId: string; sessionId: string };
}

function savedAge(profile: SkinProfile | null): ComparisonAge | undefined {
  if (profile?.version !== 4) return undefined;
  const { birthYear, age } = profile.demographics ?? {};
  const upper = birthYear === undefined ? age : new Date().getFullYear() - birthYear;
  const lower = upper === undefined ? undefined : birthYear === undefined ? upper : upper - 1;
  if (upper === undefined || lower === undefined || lower < 10 || upper >= 70 ||
    Math.floor(upper / 10) !== Math.floor(lower / 10)) return undefined;
  return `${Math.floor(upper / 10) * 10}대` as ComparisonAge;
}

export function useSkinV2Recommendation(profile: SkinProfile | null, ready: boolean) {
  const { user, ready: authReady } = useAuth();
  const owner = user?.id;
  const sessionId = useMemo(() => owner ? uuid.v4() : undefined, [owner]);
  const runId = profile?.analysis.timing.runId;
  const [selection, setSelection] = useState<{ runId: string | undefined; age?: ComparisonAge; gender?: ComparisonGender }>();
  const selected = selection?.runId === runId ? selection : undefined;
  const age = selected?.age ?? savedAge(profile);
  const gender = selected?.gender ?? (profile?.version === 4 ? profile.demographics?.gender : undefined);
  const setAge = (value: ComparisonAge) => setSelection({ runId, age: value, gender });
  const setGender = (value: ComparisonGender) => setSelection({ runId, age, gender: value });
  const prepared = useMemo(() => {
    if (!ready || !profile) return {};
    if (profile.analysis.schema !== 'skin-analysis-mobile-v4.1' || profile.analysis.acneScore === undefined) {
      return { problem: 'comparison.needV41' };
    }
    if (!age || !gender) return { problem: 'comparison.needDemographics' };
    try {
      return { request: comparisonInput(profile, age, gender) };
    } catch (error) {
      return { problem: error instanceof Error ? error.message : 'comparison.invalidScores' };
    }
  }, [profile, ready, age, gender]);
  const query = useQuery({
    queryKey: ['skin-v2-recommendations', owner, runId, prepared.request],
    queryFn: () => {
      const input = prepared.request as RecommendationComparisonInput;
      return owner && sessionId
        ? apiPost<SkinV2Result>('/api/recommendations/skin-v2/recorded',
          { sessionId, input }, { expectedUserId: owner, timeoutMs: 60000 })
        : apiPost<SkinV2Result>('/api/recommendations/skin-v2', input, { timeoutMs: 60000 });
    },
    enabled: authReady && !!prepared.request, gcTime: 0, staleTime: 0, retry: false,
  });
  return { age, gender, setAge, setGender, problem: prepared.problem, query, owner };
}
