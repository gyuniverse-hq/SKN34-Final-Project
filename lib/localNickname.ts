import AsyncStorage from '@react-native-async-storage/async-storage';
import { STORAGE_KEYS } from './storage';

const prefixes = ['기분좋은', '립바르는', '반짝이는', '볼빨간', '미소짓는', '설레는', '춤추는', '빛나는'];
const names = ['비숑', '비슈', '토끼', '여우', '수달', '고양이', '판다', '다람쥐'];

export const localNicknameKey = (owner: string) => `${STORAGE_KEYS.nickname}:${owner}`;

// The opaque account ID gives the same default on every device without storing a profile.
export function defaultNickname(owner: string) {
  let hash = 2166136261;
  for (const char of owner) hash = Math.imul(hash ^ char.charCodeAt(0), 16777619);
  const value = hash >>> 0;
  return prefixes[value % prefixes.length] + names[Math.floor(value / prefixes.length) % names.length];
}

export const validNickname = (name: string) => /^[\p{L}\p{N}]{2,16}$/u.test(name);

export async function readNickname(owner: string) {
  return await AsyncStorage.getItem(localNicknameKey(owner)) ?? defaultNickname(owner);
}

export async function saveNickname(owner: string, value: string) {
  const name = value.trim().normalize('NFC');
  if (!validNickname(name)) throw new Error('invalid_nickname');
  await AsyncStorage.setItem(localNicknameKey(owner), name);
  return name;
}
