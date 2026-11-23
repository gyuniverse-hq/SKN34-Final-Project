import AsyncStorage from '@react-native-async-storage/async-storage';
import { ApiError, apiPost } from '@/lib/api';
import { getCurrentUserId } from '@/lib/auth';
import { readSkinProfile, skinProfileKey, validateSkinProfile } from '@/lib/skinProfile';
import { STORAGE_KEYS } from '@/lib/storage';
import { useSkinProfileStore } from '@/store/skinProfileStore';
import type { SkinProfile } from '@/types/skin';

export const pendingProfileKey = (owner: string) => `${skinProfileKey(owner)}:pending`;

// Recovery and completion share the pending file. Serialize them before reading or replacing it.
let writes = Promise.resolve();
function serialize<T>(action: () => Promise<T>) {
  const next = writes.then(action);
  writes = next.then(() => {}, () => {});
  return next;
}

async function publishMemberReport(owner: string, profile: SkinProfile) {
  const key = pendingProfileKey(owner);
  let access: { subscribed: boolean };
  try {
    access = await apiPost('/api/me/skin-access/complete', { runId: profile.analysis.timing.runId }, { expectedUserId: owner });
  } catch (error) {
    if (error instanceof ApiError && error.code === 'skin_access_required') await AsyncStorage.removeItem(key);
    throw error;
  }
  await useSkinProfileStore.getState().save(profile, owner);
  await AsyncStorage.removeItem(key);
  return access.subscribed ? 'subscription' as const : 'free' as const;
}

// A lost response or a full disk after a successful claim can be retried with the same run ID.
export function recoverMemberReport(owner: string) {
  return serialize(() => recover(owner));
}

async function recover(owner: string) {
  const raw = await AsyncStorage.getItem(pendingProfileKey(owner));
  if (!raw) return;
  const profile: SkinProfile = JSON.parse(raw);
  validateSkinProfile(profile);
  try { await publishMemberReport(owner, profile); }
  catch (error) {
    if (!(error instanceof ApiError && error.code === 'skin_access_required')) throw error;
  }
}

export function registerSkinReport(profile: SkinProfile, owner: string | null) {
  return serialize(() => register(profile, owner));
}

async function register(profile: SkinProfile, owner: string | null) {
  if (await getCurrentUserId() !== owner) throw new Error('owner_changed');
  validateSkinProfile(profile);
  if (owner) {
    await AsyncStorage.setItem(pendingProfileKey(owner), JSON.stringify(profile));
    return publishMemberReport(owner, profile);
  }
  const used = await AsyncStorage.getItem(STORAGE_KEYS.guestSkinTrial) ?? (await readSkinProfile())?.analysis.timing.runId;
  if (used && used !== profile.analysis.timing.runId) throw new ApiError('Trial already used', 409, 'skin_access_required');
  await useSkinProfileStore.getState().save(profile);
  await AsyncStorage.setItem(STORAGE_KEYS.guestSkinTrial, profile.analysis.timing.runId);
  return 'free' as const;
}
