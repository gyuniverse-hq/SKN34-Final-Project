import { useCallback, useEffect, useMemo, useState } from 'react';
import { SKIN_REPORT_EXAMPLE } from '@/constants/skinCare';
import { useSkinRecommendations } from '@/lib/queries';
import { toggleConcern } from '@/lib/skinFilters';
import { buildSkinReport, ingredientExamples, sampleProductMatches } from '@/lib/skinReport';
import { buildSkinRecommendationRequest } from '@/lib/skinRecommendations';
import { useSkinProfileStore } from '@/store/skinProfileStore';
import { useSkinPreviewStore } from '@/store/skinPreviewStore';
import type { SkinConcern, SkinRecommendationRequest } from '@/types';

export function useSkinReport() {
  const profile = useSkinProfileStore((s) => s.profile);
  const preview = useSkinPreviewStore((s) => s.preview);
  const hydrate = useSkinProfileStore((s) => s.hydrate);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [selection, setSelection] = useState<SkinConcern[]>();
  const [active, setActive] = useState<SkinConcern>();
  const [request, setRequest] = useState<SkinRecommendationRequest>();
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
  const selected = selection ?? report.concerns;
  const activeConcern = active ?? report.priorities[0].concern;
  const samples = useMemo(() => sampleProductMatches(selected), [selected]);
  const recommendations = useSkinRecommendations(request);
  return {
    report, selected, activeConcern, setActive, loading, loadFailed,
    preview: profile && preview?.runId === profile.analysis.timing.runId ? preview : null,
    reload,
    example: profile === null,
    ingredients: ingredientExamples(activeConcern), samples, recommendations, live: request !== undefined,
    toggle: (c: SkinConcern) => { setSelection(toggleConcern(selected, c)); setRequest(undefined); },
    showSamples: () => setRequest(undefined),
    findProducts: () => {
      if (request) void recommendations.refetch();
      else setRequest(buildSkinRecommendationRequest(profile, selected));
    },
  };
}
