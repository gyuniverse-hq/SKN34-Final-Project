export type SkinIndicator = 'acne' | 'pore' | 'pigmentation' | 'wrinkle' | 'skinType';
export interface SkinTypePrediction {
  label: 'dry' | 'balanced' | 'oily';
  /** Mean uncalibrated softmax in dry / balanced / oily order, not diagnostic confidence. */
  probabilities: [number, number, number];
  roiCount: 3;
  scoreType: 'mean_uncalibrated_softmax';
}
export type SkinAnswer = 0 | 1 | 2 | 'unknown';
export interface SkinQuestionnaire {
  tightness: SkinAnswer;
  oiliness: SkinAnswer;
  sensitivity: SkinAnswer;
}

export interface SkinModelTiming {
  indicator: SkinIndicator;
  sourceSha256: string;
  sha256: string;
  loadMs: number;
  validationMs: number;
  preprocessingMs: number;
  inferenceMs: number;
  downloadMs?: number;
  cacheHit?: boolean;
}

export interface SkinTiming {
  runId: string;
  processId: string;
  firstInProcess: boolean;
  device: string;
  androidVersion: string;
  build: string;
  runtime: string;
  bundleVersion: string;
  alignmentMs: number;
  captureMs: number;
  imagePreparationMs: number | null;
  validationMs: number | null;
  detectionMs: number | null;
  nativeMs: number | null;
  totalMs: number;
  memoryPssKb: number | null;
  startupMs?: number;
  jpegFixtureMaxError?: number;
  models: SkinModelTiming[];
  requestMs?: number;
  serverMs?: number;
}

export interface SkinAnalysisResult {
  schema: 'skin-analysis-mobile-v1' | 'skin-analysis-mobile-v2' | 'skin-analysis-mobile-v3' | 'skin-analysis-mobile-v4' | 'skin-analysis-server-v1';
  skinType?: SkinTypePrediction;
  /** v4 only: per-ROI uncalibrated sigmoid scores, not diagnostic confidence. */
  cautionProbabilities?: Record<Exclude<keyof SkinAnalysisResult['features'], 'acne'>, number>;
  /** v4 retains the historical ROI keys but stores binary labels (0 good / 1 care), not grades. */
  features: {
    /** Present only in historical results produced with an acne model. */
    acne?: number;
    pore_grade_cheek_image_left: number;
    pore_grade_cheek_image_right: number;
    pigmentation_grade_forehead: number;
    pigmentation_grade_cheek_image_left: number;
    pigmentation_grade_cheek_image_right: number;
    wrinkle_grade_forehead: number;
    wrinkle_grade_glabella: number;
    wrinkle_grade_eye_image_left: number;
    wrinkle_grade_eye_image_right: number;
  };
  acneScore?: number;
  acneThreshold?: number;
  roiMethod: 'opencv_haar_facebox_proportions_v1' | 'opencv_yunet_facebox_proportions_v1';
  validationStatus: 'experimental_unvalidated';
  preprocessing?: 'opencv4.12-turbojpeg95-wasm-v1' | 'skin-v3-embedded-enhancement' | 'server-native-v1';
  timing: SkinTiming;
}

export interface LegacySkinProfile {
  version: 1;
  registeredAt: string;
  analysis: SkinAnalysisResult;
  questionnaire: SkinQuestionnaire;
}

export type SosChoice = 'a' | 'b' | 'c' | 'd';
export type SosQuestion = 'afterWash' | 'selfType' | 'tzoneFrequency' | 'cloggedPores' | 'tzoneOnset' | 'washFrequency';
export interface SkinSurveyV2 {
  version: 'sos-bstq-1';
  afterWash: SosChoice;
  selfType: SosChoice;
  tzoneFrequency: SosChoice;
  cloggedPores: SosChoice;
  tzoneOnset: SosChoice | 'e';
  washFrequency: SosChoice | 'e';
  redBumps: SosChoice;
  cosmeticReaction: SosChoice | 'e';
  priority: import('./index').SkinConcern;
}
export interface SkinFusionResult {
  policy: 'sos-oily-v1';
  settings: { sosMinimum: number; maxGap: number; step: number; maxWeight: number };
  sosTotal: number;
  scores: [number, number, number] | null;
  delta: [number, number, number] | null;
  type: SkinTypePrediction['label'] | 'unknown';
  reason: 'no-model' | 'already-oily' | 'low-sos' | 'large-gap' | 'adjusted';
  weight: number;
  changed: boolean;
}
export interface SkinProfileV2 {
  version: 2;
  registeredAt: string;
  analysis: SkinAnalysisResult;
  questionnaire: SkinSurveyV2;
  fusion: SkinFusionResult;
}
export interface SkinSurveyV3 {
  version: 'skin-support-1';
  postWashDryness: 'none' | 'mild' | 'marked' | 'unknown';
  afternoonTzoneOil: 'none' | 'slight' | 'marked' | 'unknown';
  cheekState: 'dry' | 'comfortable' | 'oily' | 'variable' | 'unknown';
  oilOnset: 'within1h' | 'after1to3h' | 'after3h' | 'notNoticed' | 'unknown';
  cosmeticReaction: 'none' | 'once' | 'repeated' | 'avoided' | 'notUsed' | 'unknown';
  priority: import('./index').SkinConcern;
}
export interface SkinProfileV3 {
  version: 3;
  registeredAt: string;
  analysis: SkinAnalysisResult;
  questionnaire: SkinSurveyV3;
}
export interface SupportFusionSettings {
  highSignal: number;
  lowSignal: number;
  maxTopGap: number;
  maxTargetGap: number;
  maxAdjustment: number;
  dryPostWashWeight: number;
  oilTzoneWeight: number;
}
export type SupportFusionReason = 'no-model' | 'missing-survey' | 'unsupported-survey' | 'missing-answer' |
  'invalid-answer' | 'ambiguous-survey' | 'both-high' | 'neutral' | 'model-clear' | 'target-distant' | 'adjusted-dry' | 'adjusted-oily';
export interface SupportFusionResult {
  policy: 'support-dry-oily-v1';
  settings: SupportFusionSettings;
  signals: { dry: number; oily: number } | null;
  scores: [number, number, number] | null;
  delta: [number, number, number] | null;
  type: SkinTypePrediction['label'] | 'unknown';
  reason: SupportFusionReason;
  weight: number;
  applied: boolean;
  changed: boolean;
}
export interface SkinProfileV4 {
  version: 4;
  registeredAt: string;
  analysis: SkinAnalysisResult;
  questionnaire: SkinSurveyV3;
  fusion: SupportFusionResult;
}
export type SkinProfile = LegacySkinProfile | SkinProfileV2 | SkinProfileV3 | SkinProfileV4;

export type SkinGuidance = 'loading' | 'openingCamera' | 'loadingGuide' | 'noFace' | 'multipleFaces' | 'center' | 'distance' | 'forehead' | 'straight' | 'hold' | 'capturing' | 'cameraError';
export interface SkinCameraEvent {
  guidance: SkinGuidance;
  progress: number;
  /** Opaque identifier, never a photo URI or base64 image. */
  captureId?: string;
}

export interface SkinWebRun {
  assetsUrl: string;
  photoBase64?: string;
  run: { runId: string; processId: string; firstInProcess: boolean; device: string; androidVersion: string; build: string };
}
export type SkinPoint = [number, number];
export type SkinBox = [number, number, number, number];
export interface SkinPreview {
  runId: string;
  width: number;
  height: number;
  outline: SkinPoint[];
  boxes: SkinBox[];
  jpeg: string;
}

export type SkinWebEvent = { type: 'camera'; state: SkinCameraEvent }
  | { type: 'captured' }
  | { type: 'preview-start'; runId: string; width: number; height: number; outline: SkinPoint[]; boxes: SkinBox[]; length: number }
  | { type: 'preview-chunk'; runId: string; index: number; data: string }
  | { type: 'preview-end'; runId: string }
  | { type: 'progress'; indicator: SkinIndicator }
  | { type: 'result'; result: SkinAnalysisResult }
  | { type: 'error'; code: 'photo' | 'permission' | 'model' | 'camera' | 'guide' };
