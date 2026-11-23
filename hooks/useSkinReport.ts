import { useMemo, useState } from 'react';
import { uuid } from 'expo';
import { SKIN_REPORT_EXAMPLE } from '@/constants/skinCare';
import { useAuth } from '@/lib/auth';
import { useSkincareRecommendations } from '@/lib/queries';
import { buildSkinReport, ingredientExamples } from '@/lib/skinReport';
import { deriveCareGoals, displayCareGoal } from '@/lib/skincare';
import { useOwnedSkinProfile } from '@/hooks/useOwnedSkinProfile';
import { useSkinPreviewStore } from '@/store/skinPreviewStore';
import type { SkinConcern } from '@/types';

export function useSkinReport(recommendationsEnabled = true) {
  const { profile, loading, loadFailed, reload } = useOwnedSkinProfile();
  const preview = useSkinPreviewStore((s) => s.preview);
  const [active, setActive] = useState<SkinConcern>();
  const report = useMemo(() => buildSkinReport(profile ?? SKIN_REPORT_EXAMPLE), [profile]);
  const activeConcern = active ?? report.priorities[0].concern;
  const request = useMemo(() => !loading && !loadFailed && profile ? deriveCareGoals(profile) : undefined,
    [loading, loadFailed, profile]);
  const { user, ready } = useAuth();
  const owner = user?.id;
  const runId = profile?.analysis.timing.runId;
  const sessionId = useMemo(() => owner && runId ? uuid.v4() : undefined, [owner, runId]);
  const recommendations = useSkincareRecommendations(recommendationsEnabled ? request : undefined, owner, sessionId, ready);
  return {
    report, activeConcern, setActive, loading, loadFailed,
    preview: profile && preview?.runId === profile.analysis.timing.runId ? preview : null,
    reload,
    example: profile === null,
    ingredients: displayCareGoal(activeConcern) === 'dryness'
      ? [...new Set([...ingredientExamples('dryness'), ...ingredientExamples('oiliness')])]
      : ingredientExamples(activeConcern), recommendations, owner, live: request !== undefined,
  };
}
