import { useCallback, useEffect, useMemo, useState } from 'react';
import { SKIN_REPORT_EXAMPLE } from '@/constants/skinCare';
import { useSkincareRecommendations } from '@/lib/queries';
import { toggleConcern } from '@/lib/skinFilters';
import { buildSkinReport, ingredientExamples, sampleProductMatches } from '@/lib/skinReport';
import { deriveCareGoals, skincareRequest } from '@/lib/skincare';
import { saveSkincareRecord } from '@/lib/skincareRecord';
import type { CareGoal, SkincareRequest } from '@/types/skincare';
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
  const [request, setRequest] = useState<SkincareRequest>();
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
  const primary = primaryOverride ?? derived.primary;
  const selected = selection ?? derived.secondary;
  const activeConcern = active ?? report.priorities[0].concern;
  const samples = useMemo(() => sampleProductMatches(primary ? [primary, ...selected] : selected), [primary, selected]);
  const recommendations = useSkincareRecommendations(request);
  useEffect(() => {
    if (request && recommendations.data) {
      void saveSkincareRecord(request, recommendations.data, derived.sources).then(() => setRecordFailed(false)).catch(() => setRecordFailed(true));
    }
  }, [request, recommendations.data, derived.sources]);
  return {
    recordFailed, report, primary, setPrimary: (g: CareGoal) => { setPrimaryOverride(g); setRequest(undefined); }, selected, activeConcern, setActive, loading, loadFailed,
    preview: profile && preview?.runId === profile.analysis.timing.runId ? preview : null,
    reload,
    example: profile === null,
    ingredients: ingredientExamples(activeConcern), samples, recommendations, live: request !== undefined,
    toggle: (c: SkinConcern) => { setSelection(toggleConcern(selected, c)); setRequest(undefined); },
    showSamples: () => setRequest(undefined),
    findProducts: () => {
      if (request) void recommendations.refetch();
      else if (primary) setRequest(skincareRequest(profile, primary, selected as CareGoal[]));
    },
  };
}
