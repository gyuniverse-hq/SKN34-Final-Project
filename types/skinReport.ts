import type { SkinConcern } from './index';
import type { SkinAnalysisResult, SkinQuestionnaire, SkinSurveyV2, SkinSurveyV3, SkinFusionResult, SupportFusionResult, SkinTypePrediction } from './skin';

type ReportAnalysis = Pick<SkinAnalysisResult, 'features' | 'schema' | 'skinType' | 'cautionProbabilities' | 'acneScore'>;

export type SkinReportInput = {
  version?: 1;
  registeredAt: string;
  analysis: ReportAnalysis;
  questionnaire: SkinQuestionnaire;
} | {
  version: 2;
  registeredAt: string;
  analysis: ReportAnalysis;
  questionnaire: SkinSurveyV2;
  fusion: SkinFusionResult;
} | {
  version: 3;
  registeredAt: string;
  analysis: ReportAnalysis;
  questionnaire: SkinSurveyV3;
} | {
  version: 4;
  registeredAt: string;
  analysis: ReportAnalysis;
  questionnaire: SkinSurveyV3;
  fusion: SupportFusionResult;
};
export type SkinType = 'dry' | 'oily' | 'combination' | 'balanced' | 'unknown';
export type SkinRegion = 'forehead' | 'leftCheek' | 'rightCheek' | 'glabella' | 'leftEye' | 'rightEye' | 'overall';
export interface SkinReportMetric {
  concern: SkinConcern;
  source: 'analysis' | 'combined' | 'survey' | 'unavailable';
  status: 'care' | 'good' | 'unknown';
  skinType?: SkinType;
  value: number | null;
  maximum: number | null;
  modelScore?: number;
  regions: { region: SkinRegion; value: number }[];
}
export interface SkinReport {
  supportAssessment?: { raw?: SkinTypePrediction; questionnaire: SkinSurveyV3; fusion?: SupportFusionResult };
  assessment?: { fusion: SkinFusionResult; raw?: SkinTypePrediction; questionnaire: SkinSurveyV2 };
  skinType: SkinType;
  skinTypeSource: 'analysis' | 'survey' | 'combined';
  registeredAt: string;
  reviewAt: string;
  metrics: SkinReportMetric[];
  priorities: SkinReportMetric[];
  concerns: SkinConcern[];
}
export type CareIngredient = 'hyaluronic' | 'ceramide' | 'squalane' | 'niacinamide' | 'panthenol' | 'centella' | 'salicylic' | 'adenosine';
