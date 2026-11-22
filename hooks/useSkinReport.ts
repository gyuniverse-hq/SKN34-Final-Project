import { useCallback, useEffect, useMemo, useState } from 'react';
import { SKIN_REPORT_EXAMPLE } from '@/constants/skinCare';
import { useSkinV2Recommendation } from '@/hooks/useSkinV2Recommendation';
import { buildSkinReport, ingredientExamples } from '@/lib/skinReport';
import { displayCareGoal } from '@/lib/skincare';
import { useSkinProfileStore } from '@/store/skinProfileStore';
import { useSkinPreviewStore } from '@/store/skinPreviewStore';
import type { SkinConcern } from '@/types';

export function useSkinReport() {
  const profile = useSkinProfileStore((s) => s.profile);
  const preview = useSkinPreviewStore((s) => s.preview);
  const hydrate = useSkinProfileStore((s) => s.hydrate);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [active, setActive] = useState<SkinConcern>();
  const reload = useCallback(async () => {
    setLoading(true); setLoadFailed(false);
    try { await hydrate(); } catch { setLoadFailed(true); }
    finally { setLoading(false); }
  }, [hydrate]);
  useEffect(() => {
    let mounted = true;
    void hydrate().catch(() => { if (mounted) setLoadFailed(true); })
      .finally(() => { if (mounted) setLoading(false); });
    return () => { mounted = false; };
  }, [hydrate]);
  const report = useMemo(() => buildSkinReport(profile ?? SKIN_REPORT_EXAMPLE), [profile]);
  const activeConcern = active ?? report.priorities[0].concern;
  const recommendation = useSkinV2Recommendation(profile, !loading);
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
