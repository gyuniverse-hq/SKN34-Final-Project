import type { SkinProfile } from '@/types/skin';
import { CARE_GOALS, type CareGoal, type DetectionSource, type HybridMatch, type HybridResponse, type SkincareProfileRequest } from '@/types/skincare';
import { buildSkinReport } from './skinReport';
import { surveySensitivity } from './skinSurvey';

/** One display category represents the two distinct internal care goals. */
export function displayCareGoal(goal: CareGoal): CareGoal {
  return goal === 'oiliness' ? 'dryness' : goal;
}

/** Merge the two internal balance results without duplicating a product. */
export function displayCareGroups(response: HybridResponse) {
  const groups = new Map<CareGoal, { goal: CareGoal; status: HybridResponse['coverage'][number]['status']; matches: HybridMatch[] }>();
  const order = { mapping_unavailable: 0, no_matches: 1, ok: 2 } as const;
  for (const item of response.coverage) {
    const goal = displayCareGoal(item.goal);
    const group = groups.get(goal) ?? { goal, status: item.status, matches: [] };
    if (order[item.status] > order[group.status]) group.status = item.status;
    for (const match of response.byConcern[item.goal] ?? []) {
      if (group.matches.length < 5 && !group.matches.some(m => m.product.id === match.product.id)) group.matches.push(match);
    }
    groups.set(goal, group);
  }
  const balance = groups.get('dryness');
  if (balance && response.balanceMatches) balance.matches = response.balanceMatches.slice(0, 5);
  return [...groups.values()];
}

export function deriveCareGoals(profile: SkinProfile | null): SkincareProfileRequest {
  const report = profile && buildSkinReport(profile);
  const sources = new Map<CareGoal, Set<DetectionSource>>();
  function add(goal: CareGoal, source: DetectionSource) {
    const found = sources.get(goal) ?? new Set<DetectionSource>();
    found.add(source);
    sources.set(goal, found);
  }
  for (const metric of report?.metrics ?? []) {
    if (metric.status !== 'care' || metric.source === 'unavailable') continue;
    if (metric.source === 'survey' || metric.source === 'combined') add(metric.concern, 'survey');
    if (metric.source !== 'survey') {
      add(metric.concern, ['dryness', 'oiliness'].includes(metric.concern) ? 'skinType' : 'analysis');
    }
  }
  let irritationSignal: SkincareProfileRequest['irritationSignal'] = 'unknown';
  const q = profile?.questionnaire;
  if (q) {
    if ('version' in q) {
      const sensitivity = surveySensitivity(q);
      irritationSignal = sensitivity === 'care' ? 'caution' : sensitivity === 'good' ? 'none' : 'unknown';
    } else {
      irritationSignal = q.sensitivity === 2 ? 'caution' : q.sensitivity === 0 ? 'none' : 'unknown';
    }
  }
  const detectedConcerns = CARE_GOALS.filter(g => sources.has(g))
    .map(goal => ({ goal, sources: [...sources.get(goal)!] }));
  const analysisScores: NonNullable<SkincareProfileRequest['analysisScores']> = {};
  if (profile?.analysis.schema === 'skin-analysis-mobile-v4') {
    for (const metric of report?.metrics ?? []) {
      if ((metric.concern === 'pores' || metric.concern === 'pigmentation' || metric.concern === 'wrinkles') &&
          metric.status !== 'unknown' && metric.modelScore !== undefined &&
          Number.isFinite(metric.modelScore) && metric.modelScore >= 0 && metric.modelScore <= 1) {
        analysisScores[metric.concern] = metric.modelScore;
      }
    }
  }
  return { detectedConcerns, irritationSignal,
    ...(Object.keys(analysisScores).length ? { analysisScores } : {}),
    skinType: report?.skinType === 'combination' ? 'unknown' as const : report?.skinType ?? 'unknown' };
}
