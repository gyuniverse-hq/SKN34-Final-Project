import { careTagsOf, suggestConcerns, toggleConcern } from '@/lib/skinFilters';
import { buildSkinRecommendationRequest } from '@/lib/skinRecommendations';
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

  it('keeps only known care tags in display order', () => {
    expect(careTagsOf(['demo', 'oil-control', 'hydrating', 'pore-care'])).toEqual(['hydrating', 'oil-control', 'pore-care']);
    expect(careTagsOf(['demo'])).toEqual([]);
  });
});

describe('skin recommendation request', () => {
  it('combines all four model indicators and the three survey answers', () => {
    const p = profile({
      acne: 1, pore_grade_cheek_image_left: 3,
      pigmentation_grade_forehead: 3, wrinkle_grade_eye_image_right: 3,
    }, { tightness: 2, oiliness: 2, sensitivity: 2 });
    expect(buildSkinRecommendationRequest(p)).toEqual({
      concerns: ['dryness', 'oiliness', 'sensitivity', 'blemish', 'pores', 'pigmentation', 'wrinkles'],
      limit: 8,
    });
  });

  it('does not manufacture concerns for unknown or mild survey answers', () => {
    expect(buildSkinRecommendationRequest(profile({}, {
      tightness: 'unknown', oiliness: 1, sensitivity: 0,
    })).concerns).toEqual([]);
    expect(buildSkinRecommendationRequest(null).concerns).toEqual([]);
  });

  it('respects user removal and manual additions instead of silently restoring model concerns', () => {
    const p = profile({ acne: 1 }, { sensitivity: 2 });
    expect(buildSkinRecommendationRequest(p, ['pores', 'pores', 'dryness'])).toEqual({
      concerns: ['dryness', 'pores'], limit: 8,
    });
    expect(buildSkinRecommendationRequest(p, []).concerns).toEqual([]);
    expect(buildSkinRecommendationRequest(null, ['oiliness']).concerns).toEqual(['oiliness']);
  });

  it('sends only concern codes, leaving analysis, answers and metadata on the device', () => {
    const p = profile({ acne: 1 }, { tightness: 2 });
    const original = JSON.stringify(p);
    expect(JSON.stringify(buildSkinRecommendationRequest(p))).toBe(
      '{"concerns":["dryness","blemish"],"limit":8}'
    );
    expect(JSON.stringify(p)).toBe(original);
  });
});
