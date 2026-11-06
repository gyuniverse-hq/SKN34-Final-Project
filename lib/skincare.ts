import type { SkinProfile } from '@/types/skin';
import { CARE_GOALS, type CareGoal, type SkincareRequest } from '@/types/skincare';
import { buildSkinReport } from './skinReport';
import { surveySensitivity } from './skinSurvey';

/** Initial service heuristics. Raw answers and image scores never enter the request. */
export function deriveCareGoals(profile: SkinProfile | null) {
  const sources: Partial<Record<CareGoal, string[]>> = {};
  const add = (g: CareGoal, source: string) => { (sources[g] ??= []).push(source); };
  const report = profile ? buildSkinReport(profile) : null;
  for (const g of ['pigmentation', 'wrinkles', 'pores'] as const) {
    if (report?.metrics.some(m => m.concern === g && m.status === 'care')) add(g, 'analysis');
  }
  if (report?.skinType === 'dry') add('dryness', 'skin-type');
  let irritationSignal: SkincareRequest['irritationSignal'] = 'unknown';
  let primary: CareGoal | undefined;
  if (profile) {
    const q = profile.questionnaire;
    if ('version' in q) {
      if (CARE_GOALS.includes(q.priority as CareGoal)) { primary = q.priority as CareGoal; add(primary, 'user'); }
      const sensitivity = surveySensitivity(q);
      irritationSignal = sensitivity === 'care' ? 'caution' : sensitivity === 'good' ? 'none' : 'unknown';
      if (q.version === 'skin-support-1' && (q.postWashDryness === 'marked' || q.cheekState === 'dry')) add('dryness', 'survey');
    } else {
      irritationSignal = q.sensitivity === 2 ? 'caution' : q.sensitivity === 0 ? 'none' : 'unknown';
      if (q.tightness === 2) add('dryness', 'survey');
    }
    if (irritationSignal === 'caution') add('sensitivity', 'survey');
  }
  return { primary, secondary: CARE_GOALS.filter(g => g !== primary && sources[g]), sources,
    skinType: report?.skinType === 'combination' ? 'unknown' as const : report?.skinType ?? 'unknown', irritationSignal };
}
export function skincareRequest(profile: SkinProfile | null, primaryGoal: CareGoal, secondary: readonly CareGoal[]): SkincareRequest {
  const derived = deriveCareGoals(profile);
  return { primaryGoal, secondaryGoals: CARE_GOALS.filter(g => g !== primaryGoal && secondary.includes(g)),
    skinType: derived.skinType, irritationSignal: derived.irritationSignal,
    goalPolicyVersion: 'care-goals-v2', limit: 8, ...(__DEV__ ? { includeTrace: true } : {}) };
}
