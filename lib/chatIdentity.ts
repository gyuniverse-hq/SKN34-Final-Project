import AsyncStorage from '@react-native-async-storage/async-storage';
import { createId } from '@/lib/format';
import { STORAGE_KEYS } from '@/lib/storage';

const ANONYMOUS_ID = /^[A-Za-z0-9_-]{32,128}$/;

function createAnonymousId(): string {
  // This is a random, device-local rate-limit key, not an account identifier.
  return Array.from({ length: 4 }, () => createId()).join('');
}

/** Returns a locally persisted anonymous ID without collecting personal information. */
export async function getAnonymousChatId(): Promise<string> {
  const stored = await AsyncStorage.getItem(STORAGE_KEYS.chatAnonymousId);
  if (stored && ANONYMOUS_ID.test(stored)) return stored;

  const anonymousId = createAnonymousId();
  await AsyncStorage.setItem(STORAGE_KEYS.chatAnonymousId, anonymousId);
  return anonymousId;
}
