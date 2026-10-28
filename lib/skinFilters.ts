import type { SkinConcern } from '@/types';
import type { SkinProfile } from '@/types/skin';
import { SKIN_CONCERNS } from './routes';
import { summarizeSkinResult } from './skinResult';

/**
 * Filter suggestions from the on-device profile. The user edits them before anything is sent;
 * only the chosen concern codes reach the API, never grades, answers or images.
 */
export function suggestConcerns(profile: SkinProfile | null | undefined): SkinConcern[] {
  if (!profile) return [];
  const found = new Set<SkinConcern>();
  const summary = summarizeSkinResult(profile.analysis.features);
  for (const { indicator, status } of summary.grades) {
    if (status !== 'care') continue;
    found.add(indicator === 'pore' ? 'pores' : indicator === 'pigmentation' ? 'pigmentation' : 'wrinkles');
  }
  if (summary.acneDetected) found.add('blemish');
  const { tightness, oiliness, sensitivity } = profile.questionnaire;
  if (tightness === 2) found.add('dryness');
  if (oiliness === 2) found.add('oiliness');
  if (sensitivity === 2) found.add('sensitivity');
  return SKIN_CONCERNS.filter((c) => found.has(c));
}

export function toggleConcern(concerns: readonly SkinConcern[], concern: SkinConcern): SkinConcern[] {
  const next = concerns.includes(concern) ? concerns.filter((c) => c !== concern) : [...concerns, concern];
  return SKIN_CONCERNS.filter((c) => next.includes(c));
}
