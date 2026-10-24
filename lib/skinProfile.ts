import AsyncStorage from '@react-native-async-storage/async-storage';
import { STORAGE_KEYS } from './storage';
import type { SkinAnalysisResult, SkinProfile, SkinTiming } from '@/types/skin';

const FEATURE_MAX: Record<keyof SkinAnalysisResult['features'], number> = {
  acne: 1, pore_grade_cheek_image_left: 5, pore_grade_cheek_image_right: 5,
  pigmentation_grade_forehead: 5, pigmentation_grade_cheek_image_left: 5,
  pigmentation_grade_cheek_image_right: 5, wrinkle_grade_forehead: 6,
  wrinkle_grade_glabella: 6, wrinkle_grade_eye_image_left: 6, wrinkle_grade_eye_image_right: 6,
};

export function validateSkinAnalysis(result: SkinAnalysisResult): void {
  if (result.preprocessing !== undefined && result.preprocessing !== 'opencv4.12-turbojpeg95-wasm-v1') throw new Error('skin.analysisFailed');
  if (result.schema !== 'skin-analysis-mobile-v1' || !result.features ||
      Object.keys(result.features).length !== 10 || Object.entries(FEATURE_MAX).some(([key, max]) => {
        const value = result.features[key as keyof typeof FEATURE_MAX];
        return !Number.isInteger(value) || value < 0 || value > max;
      }) || !Number.isFinite(result.acneScore) || result.acneScore < 0 || result.acneScore > 1 ||
      !(result.acneThreshold > 0 && result.acneThreshold < 1) ||
      result.features.acne !== Number(result.acneScore >= result.acneThreshold) ||
      result.roiMethod !== 'opencv_haar_facebox_proportions_v1' || result.validationStatus !== 'experimental_unvalidated' ||
      !result.timing || !Array.isArray(result.timing.models) || result.timing.models.length !== 4 ||
      new Set(result.timing.models.map(model => model.indicator)).size !== 4 ||
      !['acne', 'pore', 'pigmentation', 'wrinkle'].every(indicator => result.timing.models.some(model => model.indicator === indicator)) ||
      !Number.isFinite(result.timing.totalMs) || result.timing.totalMs < 0) throw new Error('skin.analysisFailed');
}

export async function readSkinProfile(): Promise<SkinProfile | null> {
  const raw = await AsyncStorage.getItem(STORAGE_KEYS.skinProfile);
  if (!raw) return null;
  const profile: SkinProfile = JSON.parse(raw);
  validateSkinAnalysis(profile.analysis);
  if (profile.version !== 1 || !Number.isFinite(Date.parse(profile.registeredAt)) ||
      !profile.questionnaire || ['tightness', 'oiliness', 'sensitivity'].some(key =>
        ![0, 1, 2, 'unknown'].includes(profile.questionnaire[key as keyof typeof profile.questionnaire]))) {
    throw new Error('skin.storageFailed');
  }
  return profile;
}

export async function writeSkinProfile(profile: SkinProfile) {
  validateSkinAnalysis(profile.analysis);
  await AsyncStorage.setItem(STORAGE_KEYS.skinProfile, JSON.stringify(profile));
}

let timingWrites: Promise<unknown> = Promise.resolve();
export async function readSkinTimings(): Promise<SkinTiming[]> {
  const raw = await AsyncStorage.getItem(STORAGE_KEYS.skinTimings);
  const rows = raw ? JSON.parse(raw) : [];
  if (!Array.isArray(rows)) throw new Error('skin.storageFailed');
  return rows;
}

export function appendSkinTiming(timing: SkinTiming) {
  const pending = timingWrites.catch(() => {}).then(async () => {
    const previous = await readSkinTimings();
    const next = [...previous.filter(row => row.runId !== timing.runId), timing].slice(-100);
    await AsyncStorage.setItem(STORAGE_KEYS.skinTimings, JSON.stringify(next));
  });
  timingWrites = pending;
  return pending;
}

export function clearSkinTimings() {
  const pending = timingWrites.catch(() => {}).then(() => AsyncStorage.removeItem(STORAGE_KEYS.skinTimings));
  timingWrites = pending;
  return pending;
}

export function comparableSkinTimings(rows: SkinTiming[]) {
  const last = rows.at(-1);
  return last ? rows.filter(row => row.device === last.device && row.build === last.build &&
    row.runtime === last.runtime && row.bundleVersion === last.bundleVersion && row.androidVersion === last.androidVersion) : [];
}

export function summarizeSkinTimings(rows: SkinTiming[]) {
  const values = rows.map(row => row.totalMs).sort((a, b) => a - b);
  const n = values.length;
  return n ? { count: n, min: values[0], max: values[n - 1], median: (values[Math.floor((n - 1) / 2)] + values[Math.floor(n / 2)]) / 2 } : null;
}
