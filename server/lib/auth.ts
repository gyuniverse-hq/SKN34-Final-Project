import { createClient, type SupabaseClient } from '@supabase/supabase-js';
import type { AuthUser } from '@/types';
import { serverEnv } from './env';

let client: SupabaseClient | null = null;

export function isAuthConfigured() {
  return Boolean(serverEnv.supabaseUrl && serverEnv.supabasePublishableKey);
}

function authClient() {
  const url = serverEnv.supabaseUrl;
  const key = serverEnv.supabasePublishableKey;
  if (!url || !key) return null;
  client ??= createClient(url, key, {
    auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false },
  });
  return client;
}

export function bearerToken(request: Request): string | null {
  const match = request.headers.get('authorization')?.match(/^Bearer\s+(\S+)\s*$/i);
  return match ? match[1] : null;
}

export function userFromClaims(claims: Record<string, unknown>): AuthUser | null {
  if (typeof claims.sub !== 'string' || claims.role !== 'authenticated') return null;
  return { id: claims.sub, email: typeof claims.email === 'string' ? claims.email : null };
}

/**
 * Verifies the request's Supabase access token (signature and expiry) and returns its user,
 * or `null` when the token is missing or invalid.
 */
export async function getAuthUser(request: Request): Promise<AuthUser | null> {
  const token = bearerToken(request);
  const supabase = authClient();
  if (!token || !supabase) return null;
  const { data, error } = await supabase.auth.getClaims(token);
  if (error || !data) return null;
  return userFromClaims(data.claims);
}
