import type { Product } from './index';
export const CARE_GOALS = ['dryness', 'sensitivity', 'pigmentation', 'wrinkles', 'pores', 'oiliness', 'blemish'] as const;
export type CareGoal = typeof CARE_GOALS[number];
export interface SkincareRequest {
  primaryGoal: CareGoal; secondaryGoals: CareGoal[];
  skinType: 'dry' | 'balanced' | 'oily' | 'unknown';
  irritationSignal: 'caution' | 'none' | 'unknown';
  goalPolicyVersion: 'care-goals-v1'; limit: number; includeTrace?: boolean;
}
export interface SkincareResponse {
  strategyVersion: 'skincare-ingredient-v1' | 'skincare-ingredient-cosing-v1'; dataVersion?: string;
  coverage: { goal: CareGoal; status: 'ok' | 'mapping_unavailable' | 'no_matches' }[];
  matches: { product: Product; optionId: string; optionName: string; priceKRW: number;
    matchedGoals: CareGoal[]; targetConcern: CareGoal; reasonCode: 'primary' | 'secondary' }[];
  trace?: Record<string, unknown>;
}

export type DetectionSource = 'analysis' | 'survey' | 'skinType';
export interface HybridRequest {
  primaryGoal: CareGoal;
  secondaryGoals: CareGoal[];
  balanceGoal?: 'primary' | 'secondary';
  detectedConcerns: { goal: CareGoal; sources: DetectionSource[] }[];
  skinType: SkincareRequest['skinType'];
  irritationSignal: SkincareRequest['irritationSignal'];
}
export interface HybridMatch {
  product: Product;
  optionId: string;
  optionName: string;
  priceKRW: number;
  reasons: { goal: CareGoal; sources: ('primary' | 'secondary' | 'skinProfile' | DetectionSource)[];
    ingredientCodes?: string[]; evidenceLevel?: 'ingredient_presence';
    evidenceSources?: ('research_mapping' | 'cosing_function')[] }[];
}
export interface HybridResponse {
  strategyVersion: 'skincare-hybrid-v2' | 'skincare-hybrid-v2-survey-v1' | 'skincare-hybrid-v2-survey-v2' | 'skincare-hybrid-v2-survey-v3' | 'skincare-hybrid-v2-coverage-v1' | 'skincare-hybrid-v2-blend-v1' | 'skincare-hybrid-v2-diversity-v1' | 'skincare-hybrid-v2-cosing-balance-v1' | 'skincare-hybrid-v2-cosing-only-v1';
  dataVersion: string | null;
  coverage: SkincareResponse['coverage'];
  overallTop5: HybridMatch[];
  byConcern: Partial<Record<CareGoal, HybridMatch[]>>;
  balanceMatches?: HybridMatch[];
}
