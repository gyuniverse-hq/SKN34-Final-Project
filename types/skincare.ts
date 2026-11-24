import type { Product } from './index';
export const CARE_GOALS = ['dryness', 'sensitivity', 'pigmentation', 'wrinkles', 'pores', 'oiliness', 'blemish'] as const;
export type CareGoal = typeof CARE_GOALS[number];

export type DetectionSource = 'analysis' | 'survey' | 'skinType' | 'conversation';
export interface SkincareProfileRequest {
  detectedConcerns: { goal: CareGoal; sources: DetectionSource[] }[];
  /** Mobile v4 ROI maxima and the mobile v4.1 whole-image blemish score. */
  analysisScores?: Partial<Record<'pores' | 'pigmentation' | 'wrinkles' | 'blemish', number>>;
  blemishThreshold?: number;
  skinType: 'dry' | 'balanced' | 'oily' | 'unknown';
  irritationSignal: 'caution' | 'none' | 'unknown';
}
export interface HybridMatch {
  product: Product;
  candidateId?: string;
  optionId: string;
  optionName: string;
  priceKRW: number;
  reasons: { goal: CareGoal; sources: ('skinProfile' | 'concern' | 'analysisSupport' | DetectionSource)[];
    ingredientCodes?: string[]; evidenceLevel?: 'ingredient_presence';
    evidenceSources?: ('research_mapping' | 'cosing_function')[] }[];
}
export interface HybridResponse {
  strategyVersion: 'skincare-v4';
  dataVersion: string | null;
  history?: { requestId: string; sessionId: string };
  coverage: { goal: CareGoal; status: 'ok' | 'mapping_unavailable' | 'no_matches' }[];
  overallTop5: HybridMatch[];
  overallTop10?: HybridMatch[];
  byConcern: Partial<Record<CareGoal, HybridMatch[]>>;
  balanceMatches?: HybridMatch[];
}
