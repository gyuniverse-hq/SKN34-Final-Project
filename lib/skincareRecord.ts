import AsyncStorage from '@react-native-async-storage/async-storage';
import type { SkincareRequest, SkincareResponse } from '@/types/skincare';
const KEY = 'kb.skincare.latest.v1';
export async function saveSkincareRecord(request: SkincareRequest, response: SkincareResponse, sources: unknown) {
  if (__DEV__) await AsyncStorage.setItem(KEY, JSON.stringify({ request, response, sources }));
}
export async function readSkincareRecord() { return __DEV__ ? AsyncStorage.getItem(KEY) : null; }
