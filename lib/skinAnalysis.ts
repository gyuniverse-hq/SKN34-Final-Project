import { requireNativeViewManager, requireOptionalNativeModule } from 'expo-modules-core';
import { Platform, type ViewProps } from 'react-native';
import type { ComponentType } from 'react';
import type { SkinAnalysisResult, SkinCameraEvent, SkinIndicator } from '@/types/skin';

interface SkinNativeModule {
  analyzeAsync(captureId: string): Promise<SkinAnalysisResult>;
  cancelAsync(): Promise<void>;
  addListener(event: 'onProgress', listener: (event: { indicator: SkinIndicator }) => void): { remove(): void };
}

export const skinAnalysisEnabled = process.env.EXPO_PUBLIC_ENABLE_SKIN_ANALYSIS === '1';
const native = Platform.OS === 'android' && skinAnalysisEnabled
  ? requireOptionalNativeModule<SkinNativeModule>('SkinAnalysis') : null;
export const skinAnalysisSupported = !!native;

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
