import type { Session } from '@supabase/supabase-js';
import { useEffect, useState } from 'react';
import { getSupabase } from './client';
import { AuthFlowError } from './errors';

export { isAuthConfigured } from './client';
export { authErrorCode, authErrorMessageKey } from './errors';

function requireClient() {
  const supabase = getSupabase();
  if (!supabase) throw new AuthFlowError('not_configured');
  return supabase;
}

export function useAuth() {
  const [state, setState] = useState(() => ({ session: null as Session | null, ready: getSupabase() === null }));

  useEffect(() => {
    const supabase = getSupabase();
    if (!supabase) return;
    let active = true;
    supabase.auth.getSession().then(({ data }) => {
      if (active) setState({ session: data.session, ready: true });
    });
    const { data } = supabase.auth.onAuthStateChange((_event, session) => {
      if (active) setState({ session, ready: true });
    });
    return () => {
      active = false;
      data.subscription.unsubscribe();
    };
  }, []);

  return { session: state.session, user: state.session?.user ?? null, ready: state.ready };
}

export async function signInWithEmail(email: string, password: string) {
  const { error } = await requireClient().auth.signInWithPassword({ email, password });
  if (error) throw error;
}

/** Resolves `needsVerification: true` when Supabase requires the emailed code before signing in. */
export async function signUpWithEmail(email: string, password: string) {
  const { data, error } = await requireClient().auth.signUp({ email, password });
  if (error) throw error;
  // With email confirmation on, Supabase answers an existing address with an identity-less user instead of an error.
  if (data.user && data.user.identities?.length === 0) throw new AuthFlowError('user_already_exists');
  return { needsVerification: !data.session };
}

export async function verifySignupCode(email: string, code: string) {
  const { error } = await requireClient().auth.verifyOtp({ email, token: code, type: 'signup' });
  if (error) throw error;
}

export async function resendSignupCode(email: string) {
  const { error } = await requireClient().auth.resend({ type: 'signup', email });
  if (error) throw error;
}

export async function sendPasswordResetCode(email: string) {
  const { error } = await requireClient().auth.resetPasswordForEmail(email);
  if (error) throw error;
}

/** Signs the user in with a recovery session so `updatePassword` can run. */
export async function verifyRecoveryCode(email: string, code: string) {
  const { error } = await requireClient().auth.verifyOtp({ email, token: code, type: 'recovery' });
  if (error) throw error;
}

export async function updatePassword(password: string) {
  const { error } = await requireClient().auth.updateUser({ password });
  if (error) throw error;
}

export async function signOut() {
  const { error } = await requireClient().auth.signOut({ scope: 'local' });
  if (error) throw error;
}
