import { requireNativeViewManager, requireOptionalNativeModule } from 'expo-modules-core';
import { Platform, type ViewProps } from 'react-native';
import Constants, { ExecutionEnvironment } from 'expo-constants';
import type { ComponentType } from 'react';
import type { SkinAnalysisResult, SkinCameraEvent, SkinIndicator, SkinWebRun } from '@/types/skin';

interface SkinNativeModule {
  analyzeAsync(captureId: string): Promise<SkinAnalysisResult>;
  cancelAsync(): Promise<void>;
  addListener(event: 'onProgress', listener: (event: { indicator: SkinIndicator }) => void): { remove(): void };
}

export const skinAnalysisEnabled = process.env.EXPO_PUBLIC_ENABLE_SKIN_ANALYSIS === '1';
const native = Platform.OS === 'android' && skinAnalysisEnabled
  ? requireOptionalNativeModule<SkinNativeModule>('SkinAnalysis') : null;
const hostUri = Constants.expoConfig?.hostUri;
export const skinAnalysisUsesWebView = skinAnalysisEnabled && !native && (Constants.executionEnvironment === ExecutionEnvironment.StoreClient || __DEV__) &&
  (Platform.OS === 'android' || Platform.OS === 'ios') && !!hostUri;
export const skinAnalysisSupported = !!native || skinAnalysisUsesWebView;
let webAttempts = 0;
const webSessionId = `${Constants.sessionId}-${Date.now()}`;
export function createSkinWebRun(): SkinWebRun {
  if (!skinAnalysisUsesWebView || !hostUri) throw new Error('skin.unsupported');
  const origin = new URL(hostUri.includes('://') ? hostUri : `http://${hostUri}`);
  const firstInProcess = webAttempts++ === 0;
  return { assetsUrl: `${origin.origin}/skin-runtime/`, run: {
    runId: `${webSessionId}-${webAttempts}`, processId: webSessionId,
    firstInProcess, device: Constants.deviceName || Platform.OS,
    androidVersion: `${Platform.OS} ${Platform.Version}`, build: `${Constants.expoConfig?.version || 'unknown'}:expo-go:${__DEV__ ? 'dev' : 'production-js'}`,
  } };
}

export interface SkinCameraProps extends ViewProps {
  active: boolean;
  onCaptureState: (event: { nativeEvent: SkinCameraEvent }) => void;
}

// A getter prevents Expo Go from trying to resolve a missing native view at import time.
export function getSkinCameraView(): ComponentType<SkinCameraProps> {
  if (!native) throw new Error('skin.unsupported');
  return requireNativeViewManager<SkinCameraProps>('SkinAnalysis');
}

export function analyzeSkin(captureId: string) {
  if (!native) return Promise.reject(new Error('skin.unsupported'));
  return native.analyzeAsync(captureId);
}

export async function cancelSkinAnalysis() { await native?.cancelAsync(); }
export function onSkinProgress(listener: (event: { indicator: SkinIndicator }) => void) {
  return native?.addListener('onProgress', listener);
}
