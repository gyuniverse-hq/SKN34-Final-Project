import { useQueryClient } from '@tanstack/react-query';
import { usePathname, useRouter } from 'expo-router';
import { useCallback, useEffect } from 'react';
import { agreeToTerms, needsTermsConsent } from '@/lib/account';
import { useAuth } from '@/lib/auth';
import { meQueryKey, useMe } from '@/lib/queries';
import type { MeResponse } from '@/types';

/** Screens that must stay reachable while consent is missing (sign-in flow, the consent screen, legal texts). */
const UNGATED_PATHS = ['/login', '/signup', '/reset-password', '/auth/callback', '/terms-consent'];

/**
 * Sends a signed-in user without a record of the current terms (Google sign-up, changed terms)
 * to the consent screen. When the backend cannot be reached nothing is blocked.
 */
export function useTermsConsentGate() {
  const { user } = useAuth();
  const me = useMe(user?.id);
  const router = useRouter();
  const pathname = usePathname();
  // A backend without the members migration answers without `terms`.
  const terms = me.data?.user.id === user?.id ? me.data?.terms : undefined;
  const needsConsent = !!terms && needsTermsConsent(terms);
  const ungated = UNGATED_PATHS.includes(pathname) || pathname.startsWith('/legal/');

  useEffect(() => {
    if (needsConsent && !ungated) router.push('/terms-consent');
  }, [needsConsent, ungated, router]);
}

/** Records consent and updates the cached profile so the gate does not ask again. */
export function useSaveTermsConsent() {
  const queryClient = useQueryClient();
  return useCallback(
    async (userId: string) => {
      const terms = await agreeToTerms();
      await queryClient.cancelQueries({ queryKey: meQueryKey(userId) });
      queryClient.setQueryData<MeResponse>(meQueryKey(userId), (old) => (old ? { ...old, terms } : old));
    },
    [queryClient]
  );
}
