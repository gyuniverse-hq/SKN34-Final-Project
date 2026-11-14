export type ComparisonGoal = 'pores' | 'pigmentation' | 'wrinkles';
export type ComparisonAge = '10대' | '20대' | '30대' | '40대' | '50대' | '60대';
export type ComparisonGender = '남성' | '여성';
export interface RecommendationComparisonInput {
  ageGroup: ComparisonAge;
  gender: ComparisonGender;
  skinType: '건성' | '중성' | '지성' | '복합성';
  analysisVersion: 'skin-analysis-v4';
  scoreKind: 'binary_caution_probability';
  aggregation: 'mean-cheeks-pore-tone-eyes-wrinkle-v1';
  scores: Record<ComparisonGoal, number>;
  irritationSignal?: 'caution' | 'none' | 'unknown';
}
export interface ComparisonIngredient { id: number; name: string; score: number; rank?: number }
export interface ExpandedIngredient extends ComparisonIngredient {
  concern: ComparisonGoal;
  source: 'ml_shared_tag' | 'concern_only';
  concernFunctions: string[];
  origins: { seedId: number; functions: string[]; similarity: number }[];
}
export interface ComparisonProduct {
  candidateId?: string;
  productId: string; productName: string; optionId: string;
  directIngredientIds: number[]; expandedIngredientIds: number[];
  rank: number; rankBeforeReview: number;
  review: {
    status: string; reviewCount: number | null; countBasis: string; reliability: number;
    surveyAdjustment: number;
    ratingAvg: number | null; adjustedRating: number; normalizedScore: number;
    ratingReliability: number; surveyBonus: number; surveyStatus: string;
    ratingPolicy?: 'eb_lower10' | 'legacy_20'; ratingPriorK?: number;
    ratingPosteriorMean?: number; ratingUncertaintyPenalty?: number;
    ratingLowerQuantile?: number; ratingDistributionStatus?: string;
    ratingStarCounts?: number[] | null;
    skinTypeBonus?: number;
    reviewPolicy?: 'suitability' | 'additive';
    suitabilityScore?: number | null; suitabilityLambda?: number; ratingRetention?: number;
    normalizedRating?: number; suitabilityPenalty?: number;
    suitabilitySignals?: {
      source: string; signal: string | null; status: string; ratio: number | null;
      reviewCount: number | null; priorK: number | null; baseline: number | null;
      posteriorRatio: number | null;
      posteriorSource: 'observed_plus_prior' | 'prior_only' | 'unsupported';
      goals?: ComparisonGoal[]; weight?: number; effectiveWeight?: number;
    }[];
    skinTypeReview?: {
      status: string; skinType: string; question: string; answer: string | null;
      signal: string | null; ratio: number | null; baseline: number | null;
      priorK: number | null; priorVersion: string; baselineSource: string | null;
      reliability: number; adjustment: number;
    };
    surveyPolicy: 'empirical_bayes' | 'legacy_207'; priorK: number | null;
    baselineSource: string; priorVersion: string;
    signals: { signal: string; sign: number; ratio: number | null; baseline: number | null }[];
  };
  reviewAdjusted: number | null; reviewBonus: number; ingredientScore: number; score: number;
  primaryIngredientScore?: number; secondaryIngredientScore?: number;
  secondaryIngredientEvidence?: {
    goal: ComparisonGoal; directIngredientIds: number[]; expandedIngredientIds: number[];
    mlScore: number; concernScore: number; matchedConcernFunctions: string[];
    seedMatches: { seedId: number; matchedIngredientId: number | null; strength: number; contribution: number }[];
  };
  goalWeights?: Partial<Record<ComparisonGoal, number>>;
  ingredientContribution: number; reviewContribution: number;
  mlScore: number; concernScore: number; skinTypeScore: number;
  diversityPenalty: number; selectionScore: number;
}
export interface RecommendationComparisonResult {
  history?: { requestId: string; sessionId: string };
  input: RecommendationComparisonInput; inputHash: string;
  targetConcern: ComparisonGoal; goalPolicy: string;
  sameSnapshot: boolean; overlapProductIds: string[]; limitations: string[];
  versions: { catalogVersion?: string; catalogDigest?: string };
  v1: {
    status: string; strategyVersion?: string; dataVersion?: string;
    matches: { optionId: string; product: { id: string; nameKo?: string; name: string } }[];
    selectedTrace?: { optionId: string; ingredients: string[]; mappingIds: string[]; sortKey: unknown[] }[];
  };
  v2: {
    status: string; matches: ComparisonProduct[];
    coreIngredients?: ComparisonIngredient[]; expandedIngredients?: ExpandedIngredient[];
    secondaryConcern?: ComparisonGoal | null;
    secondarySelection?: { enabled: boolean; threshold: number; status: string };
    secondaryRecommendation?: {
      goal: ComparisonGoal; coreIngredients: ComparisonIngredient[];
      expandedIngredients: ExpandedIngredient[];
      model: { version: string; sha256: string; features: Record<string, string | number> };
    } | null;
    candidateProducts?: number; candidateOptions?: number; reviewAppliedProducts?: number; shortfall?: number;
    excludedProducts?: number;
    model?: { version: string; sha256: string; features: Record<string, string | number> };
  };
}
