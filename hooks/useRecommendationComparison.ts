import { useEffect, useMemo, useState } from 'react';
import { uuid } from 'expo';
import { useMutation } from '@tanstack/react-query';
import { useOwnedSkinProfile } from '@/hooks/useOwnedSkinProfile';
import { comparisonInput, comparisonPost, fetchRecommendationComparison } from '@/lib/recommendationComparison';
import { useAuth } from '@/lib/auth';
import type { ComparisonAge, ComparisonGender, RecommendationComparisonInput, RecommendationComparisonResult } from '@/types/recommendationComparison';

export function useRecommendationComparison() {
  const { user, ready } = useAuth();
  const userId = user?.id;
  const sessionId = useMemo(() => ({ owner: userId, id: uuid.v4() }), [userId]);
  const { profile, loading, loadFailed } = useOwnedSkinProfile();
  const [age, setAge] = useState<ComparisonAge>();
  const [gender, setGender] = useState<ComparisonGender>();
  const [problem, setProblem] = useState<string>();
  const mutation = useMutation({ mutationFn: (request: { input: RecommendationComparisonInput; userId?: string; sessionId: string }) =>
    request.userId ? comparisonPost<RecommendationComparisonResult>('/compare/recorded',
      { input: request.input, sessionId: request.sessionId }, request.userId)
      : fetchRecommendationComparison(request.input), gcTime: 0 });
  useEffect(() => {
    if (profile?.version !== 4 || !profile.demographics) return;
    const { age: savedAge, birthYear, gender: savedGender } = profile.demographics;
    const upperAge = birthYear === undefined ? savedAge : new Date().getFullYear() - birthYear;
    const lowerAge = upperAge === undefined ? undefined : birthYear === undefined ? upperAge : upperAge - 1;
    if (upperAge !== undefined && lowerAge !== undefined && lowerAge >= 10 && upperAge < 70 &&
        Math.floor(lowerAge / 10) === Math.floor(upperAge / 10)) {
      setAge(previous => previous ?? `${Math.floor(upperAge / 10) * 10}대` as ComparisonAge);
    }
    if (savedGender) setGender(previous => previous ?? savedGender);
  }, [profile]);
  const run = () => {
    setProblem(undefined);
    if (!age || !gender) { setProblem('comparison.needDemographics'); return; }
    try { mutation.mutate({ input: comparisonInput(profile, age, gender), userId, sessionId: sessionId.id }); }
    catch (error) { setProblem(error instanceof Error ? error.message : 'comparison.unavailable'); }
  };
  const result = mutation.variables?.userId === userId ? mutation.data : undefined;
  return { age, setAge, gender, setGender, run, loading: loading || !ready, problem: loadFailed ? 'comparison.loadFailed' : problem, mutation, result, userId };
}
