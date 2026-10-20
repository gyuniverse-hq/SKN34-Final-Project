import AsyncStorage from '@react-native-async-storage/async-storage';
import { createJSONStorage } from 'zustand/middleware';

export const persistStorage = createJSONStorage(() => AsyncStorage);

export const STORAGE_KEYS = {
  cart: 'kb.cart.v1',
  settings: 'kb.settings.v1',
  lists: 'kb.lists.v1',
} as const;
