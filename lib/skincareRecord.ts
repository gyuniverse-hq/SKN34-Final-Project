import AsyncStorage from '@react-native-async-storage/async-storage';
import type { HybridResponse, SkincareProfileRequest } from '@/types/skincare';
const KEY = 'kb.skincare.latest.v2';
export async function saveSkincareRecord(request: SkincareProfileRequest, response: HybridResponse) {
  if (__DEV__) await AsyncStorage.setItem(KEY, JSON.stringify({ request, response }));
}
export async function readSkincareRecord() { return __DEV__ ? AsyncStorage.getItem(KEY) : null; }
