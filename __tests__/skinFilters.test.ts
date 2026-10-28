import { suggestConcerns, toggleConcern } from '@/lib/skinFilters';
import type { SkinAnalysisResult, SkinProfile, SkinQuestionnaire } from '@/types/skin';

function profile(features: Partial<SkinAnalysisResult['features']>, questionnaire: Partial<SkinQuestionnaire> = {}): SkinProfile {
  return {
    version: 1,
    registeredAt: '2026-10-01T00:00:00.000Z',
    analysis: {
      features: {
        acne: 0,
        pore_grade_cheek_image_left: 1,
        pore_grade_cheek_image_right: 1,
        pigmentation_grade_forehead: 1,
        pigmentation_grade_cheek_image_left: 1,
        pigmentation_grade_cheek_image_right: 1,
        wrinkle_grade_forehead: 1,
        wrinkle_grade_glabella: 1,
        wrinkle_grade_eye_image_left: 1,
        wrinkle_grade_eye_image_right: 1,
        ...features,
      },
    } as SkinAnalysisResult,
    questionnaire: { tightness: 0, oiliness: 0, sensitivity: 0, ...questionnaire },
  };
}

describe('skin concern suggestions', () => {
  it('suggests nothing without a saved profile or when everything is fine', () => {
    expect(suggestConcerns(null)).toEqual([]);
    expect(suggestConcerns(profile({}))).toEqual([]);
  });

  it('maps "care" grades, acne and strong survey answers to concern codes', () => {
    const p = profile(
      { acne: 1, pore_grade_cheek_image_right: 3, wrinkle_grade_glabella: 4 },
      { tightness: 2, oiliness: 1, sensitivity: 2 }
    );
    expect(suggestConcerns(p)).toEqual(['dryness', 'sensitivity', 'blemish', 'pores', 'wrinkles']);
  });

  it('ignores "unknown" survey answers', () => {
    expect(suggestConcerns(profile({}, { tightness: 'unknown', oiliness: 2 }))).toEqual(['oiliness']);
  });

  it('lets the user toggle concerns while keeping canonical order', () => {
    expect(toggleConcern(['pores'], 'dryness')).toEqual(['dryness', 'pores']);
    expect(toggleConcern(['dryness', 'pores'], 'dryness')).toEqual(['pores']);
  });
});
