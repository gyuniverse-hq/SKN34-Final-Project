export type SkinIndicator = 'acne' | 'pore' | 'pigmentation' | 'wrinkle';
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
  schema: 'skin-analysis-mobile-v1' | 'skin-analysis-server-v1';
  features: {
    acne: number;
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
  acneScore: number;
  acneThreshold: number;
  roiMethod: 'opencv_haar_facebox_proportions_v1' | 'opencv_yunet_facebox_proportions_v1';
  validationStatus: 'experimental_unvalidated';
  preprocessing?: 'opencv4.12-turbojpeg95-wasm-v1' | 'server-native-v1';
  timing: SkinTiming;
}

export interface SkinProfile {
  version: 1;
  registeredAt: string;
  analysis: SkinAnalysisResult;
  questionnaire: SkinQuestionnaire;
}

export type SkinGuidance = 'loading' | 'noFace' | 'multipleFaces' | 'center' | 'distance' | 'forehead' | 'straight' | 'hold' | 'capturing' | 'cameraError';
export interface SkinCameraEvent {
  guidance: SkinGuidance;
  progress: number;
  /** Opaque identifier, never a photo URI or base64 image. */
  captureId?: string;
}

export interface SkinWebRun {
  assetsUrl: string;
  run: { runId: string; processId: string; firstInProcess: boolean; device: string; androidVersion: string; build: string };
}
export type SkinWebEvent = { type: 'camera'; state: SkinCameraEvent }
  | { type: 'captured' }
  | { type: 'progress'; indicator: SkinIndicator }
  | { type: 'result'; result: SkinAnalysisResult }
  | { type: 'error'; code: 'photo' | 'permission' | 'model' };
