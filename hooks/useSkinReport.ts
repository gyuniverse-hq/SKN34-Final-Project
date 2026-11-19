import { useMemo, useState } from 'react';
import { SKIN_REPORT_EXAMPLE } from '@/constants/skinCare';
import { useSkinV2Recommendation } from '@/hooks/useSkinV2Recommendation';
import { buildSkinReport, ingredientExamples } from '@/lib/skinReport';
import { displayCareGoal } from '@/lib/skincare';
import { useOwnedSkinProfile } from '@/hooks/useOwnedSkinProfile';
import { useSkinPreviewStore } from '@/store/skinPreviewStore';
import type { SkinConcern } from '@/types';

export function useSkinReport(recommendationsEnabled = true) {
  const { profile, loading, loadFailed, reload } = useOwnedSkinProfile();
  const preview = useSkinPreviewStore((s) => s.preview);
  const [active, setActive] = useState<SkinConcern>();
  const report = useMemo(() => buildSkinReport(profile ?? SKIN_REPORT_EXAMPLE), [profile]);
  const activeConcern = active ?? report.priorities[0].concern;
  const recommendation = useSkinV2Recommendation(recommendationsEnabled ? profile : null, !loading && recommendationsEnabled);
  return {
    report, activeConcern, setActive, loading, loadFailed,
    preview: profile && preview?.runId === profile.analysis.timing.runId ? preview : null,
    reload,
    example: profile === null,
    ingredients: displayCareGoal(activeConcern) === 'dryness'
      ? [...new Set([...ingredientExamples('dryness'), ...ingredientExamples('oiliness')])]
      : ingredientExamples(activeConcern), recommendation, live: !loading && profile !== null,
  };
}
