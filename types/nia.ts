export interface NiaTiming {
  n: number;
  mean_ms: number;
  p50_ms: number;
  p95_ms: number;
  samples_ms: number[];
}

export interface NiaModelMetadata {
  id: string;
  task: string;
  checkpoint: string;
  sha256: string;
  architecture: string;
  outputs: number;
  resolution: number;
  device: string;
  gpu: string | null;
  gpu_resident_bytes: number | null;
  load_ms: number;
  warmup_ms: number;
  source_commit: string;
  libraries: Record<string, string>;
}

export interface NiaStatus {
  source: string;
  config_exists: boolean;
  models: {
    id: string;
    task: string;
    areas: Record<string, number[]>;
    present: boolean;
    loaded: boolean;
    metadata: NiaModelMetadata | null;
  }[];
  errors: Record<string, string>;
  dataset_configured: boolean;
  previews_allowed: boolean;
  acne?: { configured: boolean; present: boolean; loaded: boolean };
}

export interface NiaPreprocessing {
  original_size: number[];
  requested_bbox: number[] | null;
  crop: number[] | null;
  input_size: number[];
  preview?: string;
  method: string;
}

export interface NiaPrediction {
  model: NiaModelMetadata;
  area: string;
  mode: 'class' | 'regression';
  prediction: {
    grade?: number;
    probabilities?: number[];
    value?: number;
    unit?: string;
    normalized_value?: number;
    multiplier?: number;
  };
  preprocessing: NiaPreprocessing;
  preprocessing_ms: number;
  inference: NiaTiming;
  server_ms: number;
  gpu_peak_process_bytes: number | null;
}

export interface NiaInference {
  results: NiaPrediction[];
  sequence_server_ms: number;
  roi_source: string;
}

export interface NiaMetrics {
  n: number;
  mae: number;
  accuracy?: number;
  within_one?: number;
  macro_f1?: number;
  rmse?: number;
  pearson?: number | null;
  truth?: number[];
  predicted?: number[];
  confusion?: number[][];
  per_grade?: { grade: number; support: number; predicted: number; precision: number; recall: number; f1: number }[];
}

export interface NiaSample {
  id: string;
  area: string;
  device: string;
  truth: number;
  prediction: number;
  error: number;
  inference_ms: number;
}

export interface NiaReport {
  model: NiaModelMetadata;
  settings: Record<string, unknown>;
  dataset: { leakage: { status: 'unverified' | 'overlap' | 'no_overlap'; comparisons: Record<string, number> } };
  mode: 'class' | 'regression';
  unit?: string;
  metrics: NiaMetrics;
  groups: Record<string, Record<string, NiaMetrics>>;
  timing: NiaTiming;
  preprocessing: NiaTiming;
  sample_server: NiaTiming;
  server_ms: number;
  gpu_peak_process_bytes: number | null;
  samples: NiaSample[];
}

export interface NiaJob {
  id: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  completed: number;
  total: number | null;
  report: NiaReport | null;
  error?: string;
}

export type NiaPhotoFeature = 'dryness' | 'moisture' | 'pore_grade' | 'pore_value' | 'pigmentation_grade' | 'pigmentation_value' | 'wrinkle_grade' | 'wrinkle_roughness' | 'sagging' | 'elasticity';
export type NiaPhotoRegion = 'full_image' | 'forehead' | 'glabella' | 'eye_image_left' | 'eye_image_right' | 'cheek_image_left' | 'cheek_image_right' | 'lips' | 'chin';
export interface NiaPhotoRow {
  key: string;
  area: string;
  region: NiaPhotoRegion;
  facepart: number;
  status: 'predicted' | 'failed' | 'unavailable';
  value: number | null;
  result?: NiaPrediction;
  error?: string;
}
export interface NiaPhotoReport {
  status: 'complete' | 'partial' | 'no_results';
  predicted: number;
  expected: number;
  server_ms: number;
  acne?: NiaAcneResult;
  roi: { original_size: number[]; face_bbox: number[]; method: string; training_annotation_match: boolean; boxes: Record<string, number[]> };
  groups: Record<NiaPhotoFeature, { task: string; rows: NiaPhotoRow[] }>;
  ml_input: {
    acne?: NiaAcneResult;
    schema_version: string;
    features: Record<string, number | null>;
    feature_status: Record<string, 'predicted' | 'failed' | 'unavailable' | 'unsupported'>;
    provenance: Record<string, { task: string; model_id: string; checkpoint_sha256: string; region: NiaPhotoRegion; crop: number[]; unit: string; grade_range: number[] | null; original_unit_multiplier: number | null }>;
    roi_method: string;
    validation_status: string;
    training_roi_match: boolean;
    softmax_calibrated: boolean;
    unsupported: string[];
  };
}
export interface NiaPhotoJob extends Omit<NiaJob, 'report'> {
  kind: 'profile';
  report: NiaPhotoReport | null;
}

export interface NiaAcneResult {
  status: 'predicted' | 'failed';
  label: 0 | 1 | null;
  score: number | null;
  threshold?: number;
  score_type?: 'sigmoid_uncalibrated';
  model_sha256?: string;
  validation_status?: string;
  inference_ms?: number;
  error?: string;
}

/** Data and actions supplied by the development screen to presentation components. */
export interface NiaPhotoControls {
  image?: { uri: string; width: number; height: number };
  job?: NiaPhotoJob;
  busy: boolean;
  error: string;
  details: boolean;
  setDetails: (value: boolean) => void;
  pick: () => Promise<void>;
  analyze: () => Promise<void>;
  exportJson: () => Promise<void>;
}

export interface NiaDashboardControls {
  preview?: { uri: string; index: number };
  error: string;
  exportReport: (format: 'json' | 'csv') => Promise<void>;
  showSample: (index: number) => Promise<void>;
}
