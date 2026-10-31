/** Prototype content only. Replace the mappings with reviewed editorial data, not model output. */
export const CARE_INGREDIENTS = {
  dryness: ['hyaluronic', 'ceramide', 'squalane'],
  oiliness: ['niacinamide', 'panthenol'],
  sensitivity: ['panthenol', 'centella', 'ceramide'],
  blemish: ['centella', 'panthenol'],
  pores: ['niacinamide', 'salicylic'],
  pigmentation: ['niacinamide', 'panthenol'],
  wrinkles: ['adenosine', 'ceramide'],
} as const;

export const SKIN_SAMPLE_PRODUCTS = [
  { id: 'sample-serum', name: 'serum', priceKRW: 24000, concerns: ['dryness', 'sensitivity', 'pigmentation'], ingredients: ['hyaluronic', 'panthenol'] },
  { id: 'sample-cream', name: 'cream', priceKRW: 28000, concerns: ['dryness', 'sensitivity', 'wrinkles'], ingredients: ['ceramide', 'squalane'] },
  { id: 'sample-cleanser', name: 'cleanser', priceKRW: 16000, concerns: ['oiliness', 'pores', 'blemish'], ingredients: ['centella', 'panthenol'] },
  { id: 'sample-sun', name: 'sun', priceKRW: 22000, concerns: ['pigmentation', 'sensitivity'], ingredients: ['niacinamide', 'panthenol'] },
] as const;

/** Never written to skinProfileStore or passed off as a completed model run. */
export const SKIN_REPORT_EXAMPLE = {
  registeredAt: '2026-10-29T00:00:00.000Z',
  analysis: {
    schema: 'skin-analysis-server-v1',
    features: {
      acne: 0, pore_grade_cheek_image_left: 2, pore_grade_cheek_image_right: 3,
      pigmentation_grade_forehead: 2, pigmentation_grade_cheek_image_left: 1, pigmentation_grade_cheek_image_right: 2,
      wrinkle_grade_forehead: 1, wrinkle_grade_glabella: 2, wrinkle_grade_eye_image_left: 1, wrinkle_grade_eye_image_right: 2,
    },
  },
  questionnaire: { tightness: 2, oiliness: 0, sensitivity: 1 },
} as const;
