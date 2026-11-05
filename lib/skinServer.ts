import { fetch as expoFetch } from 'expo/fetch';
import { getAccessToken } from '@/lib/auth';
import { TRUSTED_SKIN_API_ORIGIN } from '@/constants/skinServer';
import { validateSkinAnalysis } from './skinProfile';
import type { CapturedSkinPhoto } from './skinCapture';
import type { SkinAnalysisResult, SkinWebRun } from '@/types/skin';

export class SkinServerError extends Error {
  constructor(public readonly code: string) { super(code); }
}

/** Explicit, development-only exception for skin analysis; other auth stays unchanged. */
export function skinServerUsesTestAuth(): boolean {
  return __DEV__ && process.env.EXPO_PUBLIC_SKIN_AUTH_MODE === 'test-token';
}

export function validateSkinServerAuth(testToken?: string): void {
  const mode = process.env.EXPO_PUBLIC_SKIN_AUTH_MODE;
  if (mode && mode !== 'supabase' && mode !== 'test-token') throw new SkinServerError('CONFIG_REQUIRED');
  if (mode === 'test-token') {
    if (!__DEV__) throw new SkinServerError('TEST_MODE_DISABLED');
    if (!testToken || !/^[\x21-\x7e]{32,4096}$/.test(testToken)) throw new SkinServerError('UNAUTHORIZED');
  }
}

export async function getSkinServerToken(testToken?: string): Promise<string | null> {
  validateSkinServerAuth(testToken);
  return skinServerUsesTestAuth() ? testToken! : getAccessToken();
}

export function skinApiUrl(configured: string | undefined): string {
  if (!configured) throw new SkinServerError('CONFIG_REQUIRED');
  const url = new URL(configured);
  if (url.origin !== TRUSTED_SKIN_API_ORIGIN || url.username || url.password ||
      url.search || url.hash || !['', '/'].includes(url.pathname)) throw new SkinServerError('UNTRUSTED_SERVER');
  return url.origin + '/analyze';
}

function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new SkinServerError('INVALID_RESULT');
  return value as Record<string, unknown>;
}

export function adaptSkinServerResult(raw: unknown, context: SkinWebRun['run'], photo: CapturedSkinPhoto,
  requestMs: number, totalMs: number): SkinAnalysisResult {
  const response = record(raw), execution = record(response.execution), acne = record(response.acne);
  const features = record(response.features), statuses = record(response.feature_status);
  if (response.schema_version !== 'skin-recommendation-features-v1' || response.status !== 'complete' ||
      response.validation_status !== 'experimental_unvalidated' ||
      response.roi_method !== 'opencv_yunet_facebox_proportions_v1' ||
      Object.keys(statuses).length !== 10 || Object.keys(features).some(key => statuses[key] !== 'predicted') ||
      acne.status !== 'predicted' || acne.label !== features.acne || execution.runtime !== 'pytorch-cuda') throw new SkinServerError('INVALID_RESULT');
  const result: SkinAnalysisResult = {
    schema: 'skin-analysis-server-v1', features: { ...features } as SkinAnalysisResult['features'],
    acneScore: acne.score as number, acneThreshold: acne.threshold as number,
    roiMethod: 'opencv_yunet_facebox_proportions_v1', validationStatus: 'experimental_unvalidated',
    preprocessing: 'server-native-v1',
    timing: { ...context, runtime: 'pytorch-cuda', bundleVersion: execution.bundleVersion as string,
      alignmentMs: photo.alignmentMs, captureMs: photo.captureMs, totalMs, requestMs,
      serverMs: execution.serverMs as number, memoryPssKb: null, models: [],
      imagePreparationMs: null, validationMs: null, detectionMs: null, nativeMs: null },
  };
  try { validateSkinAnalysis(result); } catch { throw new SkinServerError('INVALID_RESULT'); }
  return result;
}

/** Only the exact tunnel approved by the user may receive these bytes/tokens. */
export async function uploadSkinPhoto(photo: CapturedSkinPhoto, run: SkinWebRun['run'], signal: AbortSignal,
  dependencies = { fetch: expoFetch, getToken: getSkinServerToken, url: process.env.EXPO_PUBLIC_SKIN_API_URL },
  testToken?: string): Promise<SkinAnalysisResult> {
  const url = skinApiUrl(dependencies.url);
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal.addEventListener('abort', abort, { once: true });
  if (signal.aborted) abort();
  const timer = setTimeout(abort, 30000), started = performance.now();
  try {
    const token = await dependencies.getToken(testToken);
    testToken = undefined;
    if (!token) throw new SkinServerError('UNAUTHORIZED');
    if (controller.signal.aborted) throw new SkinServerError('CANCELLED');
    const requestAt = performance.now();
    const response = await dependencies.fetch(url, { method: 'POST',
      headers: { 'Content-Type': 'image/jpeg', Authorization: `Bearer ${token}`, Accept: 'application/json' },
      body: Uint8Array.from(photo.bytes).buffer, signal: controller.signal,
      redirect: 'error', credentials: 'omit' });
    if (response.redirected || (response.url && response.url !== url)) throw new SkinServerError('UNTRUSTED_SERVER');
    const body: unknown = await response.json();
    if (controller.signal.aborted) throw new SkinServerError('CANCELLED');
    if (!response.ok) throw new SkinServerError(typeof record(body).code === 'string' ? record(body).code as string : 'NETWORK');
    return adaptSkinServerResult(body, run, photo, performance.now() - requestAt,
      photo.captureMs + photo.handoffMs + performance.now() - started);
  } finally {
    testToken = undefined;
    clearTimeout(timer); signal.removeEventListener('abort', abort);
  }
}
