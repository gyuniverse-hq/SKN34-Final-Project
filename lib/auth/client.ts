import AsyncStorage from '@react-native-async-storage/async-storage';
import { createClient, type SupabaseClient } from '@supabase/supabase-js';
import { AppState, Platform } from 'react-native';

const SUPABASE_URL = process.env.EXPO_PUBLIC_SUPABASE_URL;
const SUPABASE_PUBLISHABLE_KEY = process.env.EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY;

let client: SupabaseClient | null = null;

export function isAuthConfigured() {
  return Boolean(SUPABASE_URL && SUPABASE_PUBLISHABLE_KEY);
}

/**
 * Lazily created so web server rendering, which has no device storage, never builds a client.
 * Returns `null` there and when the Supabase environment variables are missing.
 */
export function getSupabase(): SupabaseClient | null {
  if (!SUPABASE_URL || !SUPABASE_PUBLISHABLE_KEY) return null;
  if (Platform.OS === 'web' && typeof window === 'undefined') return null;
  if (!client) {
    const created = createClient(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, {
      auth: {
        storage: AsyncStorage,
        autoRefreshToken: true,
        persistSession: true,
        detectSessionInUrl: false,
      },
    });
    if (Platform.OS !== 'web') {
      AppState.addEventListener('change', (state) => {
        if (state === 'active') created.auth.startAutoRefresh();
        else created.auth.stopAutoRefresh();
      });
    }
    client = created;
  }
  return client;
}
