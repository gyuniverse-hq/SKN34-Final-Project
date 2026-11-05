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
  strategyVersion: 'skincare-ingredient-v1'; dataVersion?: string;
  coverage: { goal: CareGoal; status: 'ok' | 'mapping_unavailable' | 'no_matches' }[];
  matches: { product: Product; optionId: string; optionName: string; priceKRW: number;
    matchedGoals: CareGoal[]; targetConcern: CareGoal; reasonCode: 'primary' | 'secondary' }[];
  trace?: Record<string, unknown>;
}
