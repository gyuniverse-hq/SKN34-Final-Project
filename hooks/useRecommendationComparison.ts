import { useEffect, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useSkinProfileStore } from '@/store/skinProfileStore';
import { comparisonInput, fetchRecommendationComparison } from '@/lib/recommendationComparison';
import type { ComparisonAge, ComparisonGender } from '@/types/recommendationComparison';

export function useRecommendationComparison() {
  const profile = useSkinProfileStore(s => s.profile);
  const hydrate = useSkinProfileStore(s => s.hydrate);
  const [age, setAge] = useState<ComparisonAge>();
  const [gender, setGender] = useState<ComparisonGender>();
  const [problem, setProblem] = useState<string>();
  const [loading, setLoading] = useState(true);
  const mutation = useMutation({ mutationFn: fetchRecommendationComparison, gcTime: 0 });
  useEffect(() => {
    let active = true;
    void hydrate().catch(() => { if (active) setProblem('comparison.loadFailed'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [hydrate]);
  const run = () => {
    setProblem(undefined);
    if (!age || !gender) { setProblem('comparison.needDemographics'); return; }
    try { mutation.mutate(comparisonInput(profile, age, gender)); }
    catch (error) { setProblem(error instanceof Error ? error.message : 'comparison.unavailable'); }
  };
  return { age, setAge, gender, setGender, run, loading, problem, mutation };
}
