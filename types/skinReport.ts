import type { SkinConcern } from './index';
import type { SkinAnalysisResult, SkinQuestionnaire } from './skin';

export type SkinReportInput = {
  registeredAt: string;
  analysis: Pick<SkinAnalysisResult, 'features' | 'schema' | 'skinType'>;
  questionnaire: SkinQuestionnaire;
};
export type SkinType = 'dry' | 'oily' | 'combination' | 'balanced' | 'unknown';
export type SkinRegion = 'forehead' | 'leftCheek' | 'rightCheek' | 'glabella' | 'leftEye' | 'rightEye' | 'overall';
export interface SkinReportMetric {
  concern: SkinConcern;
  source: 'analysis' | 'combined' | 'survey' | 'unavailable';
  status: 'care' | 'fair' | 'good' | 'unknown';
  skinType?: SkinType;
  value: number | null;
  maximum: number | null;
  regions: { region: SkinRegion; value: number }[];
}
export interface SkinReport {
  skinType: SkinType;
  skinTypeSource: 'analysis' | 'survey' | 'combined';
  registeredAt: string;
  reviewAt: string;
  metrics: SkinReportMetric[];
  priorities: SkinReportMetric[];
  concerns: SkinConcern[];
}
export type CareIngredient = 'hyaluronic' | 'ceramide' | 'squalane' | 'niacinamide' | 'panthenol' | 'centella' | 'salicylic' | 'adenosine';
export interface SkinSampleProduct {
  id: string;
  name: 'serum' | 'cream' | 'cleanser' | 'sun';
  priceKRW: number;
  concerns: readonly SkinConcern[];
  ingredients: readonly CareIngredient[];
}
