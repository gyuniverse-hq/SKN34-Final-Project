import AsyncStorage from '@react-native-async-storage/async-storage';
import { createJSONStorage } from 'zustand/middleware';

export const persistStorage = createJSONStorage(() => AsyncStorage);

export const STORAGE_KEYS = {
  cart: 'kb.cart.v1',
  compare: 'kb.compare.v1',
  settings: 'kb.settings.v1',
  lists: 'kb.lists.v1',
  skinProfile: 'kb.skin-profile.v1',
  firstArInvitation: 'kb.first-ar-invitation.v1',
  guestSkinTrial: 'kb.guest-skin-trial.v1',
  skinTimings: 'kb.skin-timings.v1',
  chatAnonymousId: 'kb.chat-anonymous-id.v1',
  chatRoomDeletion: 'kb.chat-room-deletion.v1',
  chatRequestRecovery: 'kb.chat-request-recovery.v1',
  accountDeletion: 'kb.account-deletion.v1',
  recentSearches: 'kb.recent-searches.v1',
} as const;

export function chatRoomDeletionPrefix(owner?: string) {
  const prefix = `${STORAGE_KEYS.chatRoomDeletion}:`;
  return owner === undefined ? prefix : `${prefix}${encodeURIComponent(owner)}:`;
}

export function chatRoomDeletionKey(owner: string, serverId: string) {
  return `${chatRoomDeletionPrefix(owner)}${serverId}`;
}

export function chatRequestRecoveryPrefix(owner?: string, serverId?: string) {
  const prefix = `${STORAGE_KEYS.chatRequestRecovery}:`;
  if (owner === undefined) return prefix;
  const ownerPrefix = `${prefix}${encodeURIComponent(owner)}:`;
  return serverId === undefined ? ownerPrefix : `${ownerPrefix}${serverId}:`;
}

export function chatRequestRecoveryKey(owner: string, serverId: string, requestId: string) {
  return `${chatRequestRecoveryPrefix(owner, serverId)}${requestId}`;
}
