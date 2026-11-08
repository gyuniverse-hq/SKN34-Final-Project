import { useCallback, useEffect, useMemo, useState } from 'react';
import { SKIN_REPORT_EXAMPLE } from '@/constants/skinCare';
import { useSkincareRecommendations } from '@/lib/queries';
import { toggleConcern } from '@/lib/skinFilters';
import { buildSkinReport, ingredientExamples } from '@/lib/skinReport';
import { deriveCareGoals, displayCareGoal, skincareRequest } from '@/lib/skincare';
import { saveSkincareRecord } from '@/lib/skincareRecord';
import type { CareGoal } from '@/types/skincare';
import { useSkinProfileStore } from '@/store/skinProfileStore';
import { useSkinPreviewStore } from '@/store/skinPreviewStore';
import type { SkinConcern } from '@/types';

export function useSkinReport() {
  const profile = useSkinProfileStore((s) => s.profile);
  const preview = useSkinPreviewStore((s) => s.preview);
  const hydrate = useSkinProfileStore((s) => s.hydrate);
  const [loading, setLoading] = useState(true);
  const [recordFailed, setRecordFailed] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const [selection, setSelection] = useState<SkinConcern[]>();
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
  const derived = useMemo(() => deriveCareGoals(profile), [profile]);
  const [primaryOverride, setPrimaryOverride] = useState<CareGoal>();
  const rawPrimary = primaryOverride ?? derived.primary ?? (profile ? report.priorities[0]?.concern : undefined);
  const primary = rawPrimary ? displayCareGoal(rawPrimary) : undefined;
  const selected = useMemo(() => [...new Set((selection ?? []).map(displayCareGoal))].filter(g => g !== primary), [selection, primary]);
  const activeConcern = active ?? report.priorities[0].concern;
  const request = useMemo(() => !loading && profile && primary
    ? skincareRequest(profile, primary, selected as CareGoal[]) : undefined, [loading, profile, primary, selected]);
  const recommendations = useSkincareRecommendations(request);
  useEffect(() => {
    if (request && recommendations.data) {
      void saveSkincareRecord(request, recommendations.data).then(() => setRecordFailed(false)).catch(() => setRecordFailed(true));
    }
  }, [request, recommendations.data]);
  return {
    recordFailed, report, primary, setPrimary: setPrimaryOverride, selected, activeConcern, setActive, loading, loadFailed,
    preview: profile && preview?.runId === profile.analysis.timing.runId ? preview : null,
    reload,
    suggested: [...new Set(derived.detectedConcerns.map(c => displayCareGoal(c.goal)))],
    example: profile === null,
    ingredients: displayCareGoal(activeConcern) === 'dryness'
      ? [...new Set([...ingredientExamples('dryness'), ...ingredientExamples('oiliness')])]
      : ingredientExamples(activeConcern), recommendations, live: request !== undefined,
    toggle: (c: SkinConcern) => { setSelection(toggleConcern(selected, c)); },
  };
}
