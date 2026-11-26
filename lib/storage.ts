import AsyncStorage from '@react-native-async-storage/async-storage';
import { createJSONStorage } from 'zustand/middleware';

export const persistStorage = createJSONStorage(() => AsyncStorage);

export const STORAGE_KEYS = {
  rewards: 'kb.rewards.v1',
  nickname: 'kb.nickname.v1',
  cart: 'kb.cart.v1',
  compare: 'kb.compare.v1',
  settings: 'kb.settings.v1',
  lists: 'kb.lists.v1',
  skinProfile: 'kb.skin-profile.v1',
  firstArInvitation: 'kb.first-ar-invitation.v1',
  guestSkinTrial: 'kb.guest-skin-trial.v1',
  skinTimings: 'kb.skin-timings.v1',
  chatAnonymousId: 'kb.chat-anonymous-id.v1',
  recentSearches: 'kb.recent-searches.v1',
} as const;
