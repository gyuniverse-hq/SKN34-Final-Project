import { surveySensitivity } from './skinSurvey';
import type { SkinConcern } from '@/types';
import type { SkinProfile } from '@/types/skin';
import { SKIN_CONCERNS } from './routes';
import { summarizeSkinResult } from './skinResult';
import { resolveSkinType } from './skinType';

/**
 * Filter suggestions from the on-device profile. The user edits them before anything is sent;
 * only the chosen concern codes reach the API, never grades, answers or images.
 */
export function suggestConcerns(profile: SkinProfile | null | undefined): SkinConcern[] {
  if (!profile) return [];
  const found = new Set<SkinConcern>();
  const summary = summarizeSkinResult(profile.analysis.features, profile.analysis.schema);
  for (const { indicator, status } of summary.grades) {
    if (status !== 'care') continue;
    found.add(indicator === 'pore' ? 'pores' : indicator === 'pigmentation' ? 'pigmentation' : 'wrinkles');
  }
  if (summary.acneDetected) found.add('blemish');
  const skinType = profile.version === 2 || profile.version === 4
    ? { type: profile.fusion.type, source: 'analysis' }
    : profile.version === 3 ? { type: profile.analysis.skinType?.label ?? 'unknown', source: 'analysis' }
      : resolveSkinType(profile.analysis.skinType, profile.questionnaire);
  if (profile.version === 1) {
    const { tightness, oiliness, sensitivity } = profile.questionnaire;
    if (tightness === 2) found.add('dryness');
    if (oiliness === 2) found.add('oiliness');
    if (sensitivity === 2) found.add('sensitivity');
  } else {
    if (surveySensitivity(profile.questionnaire) === 'care') found.add('sensitivity');
    found.add(profile.questionnaire.priority);
  }
  if (skinType.source !== 'survey' && skinType.type === 'dry') found.add('dryness');
  if (skinType.source !== 'survey' && skinType.type === 'oily') found.add('oiliness');
  const concerns = SKIN_CONCERNS.filter((c) => found.has(c));
  return profile.version !== 1 ? [profile.questionnaire.priority, ...concerns.filter(c => c !== profile.questionnaire.priority)] : concerns;
}

/** Product care tags in display order; must match CONCERN_TAGS in backend/api catalog_service.py. */
export const CARE_TAGS = ['hydrating', 'soothing', 'oil-control', 'blemish-care', 'pore-care', 'brightening', 'firming'] as const;
export type CareTag = (typeof CARE_TAGS)[number];

export const CONCERN_TO_TAGS: Record<SkinConcern, readonly CareTag[]> = {
  dryness: ['hydrating'],
  oiliness: ['oil-control'],
  sensitivity: ['soothing'],
  blemish: ['blemish-care'],
  pores: ['pore-care'],
  pigmentation: ['brightening'],
  wrinkles: ['firming'],
};

export function careTagsOf(tags: readonly string[]): CareTag[] {
  return CARE_TAGS.filter((tag) => tags.includes(tag));
}

export function toggleConcern(concerns: readonly SkinConcern[], concern: SkinConcern): SkinConcern[] {
  const next = concerns.includes(concern) ? concerns.filter((c) => c !== concern) : [...concerns, concern];
  return SKIN_CONCERNS.filter((c) => next.includes(c));
}
