import type { SkinConcern, SkinRecommendationRequest } from '@/types';
import type { SkinProfile } from '@/types/skin';
import { SKIN_CONCERNS } from './routes';
import { suggestConcerns } from './skinFilters';

/** Raw model output and questionnaire answers stay on the device. An explicit selection replaces suggestions. */
export function buildSkinRecommendationRequest(
  profile: SkinProfile | null,
  selected?: readonly SkinConcern[]
): SkinRecommendationRequest {
  const concerns = selected ?? suggestConcerns(profile);
  return { concerns: SKIN_CONCERNS.filter((c) => concerns.includes(c)), limit: 8 };
}
