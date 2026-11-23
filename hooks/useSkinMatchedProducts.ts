import { useMemo } from 'react';
import { useOwnedSkinProfile } from '@/hooks/useOwnedSkinProfile';
import { useSkinAccess } from '@/hooks/useSkinAccess';
import { useProducts } from '@/lib/queries';
import { suggestConcerns } from '@/lib/skinFilters';

export function useSkinMatchedProducts() {
  const { profile, loading, loadFailed, reload } = useOwnedSkinProfile();
  const access = useSkinAccess();
  const visible = access.subscribed && !loading && !loadFailed && profile !== null;
  const concerns = useMemo(() => suggestConcerns(profile), [profile]);
  const products = useProducts({ category: 'skincare', concerns }, visible);
  const checking = loading || (profile !== null && !access.ready && !access.error);
  const needsSubscription = !access.subscribed && (profile !== null || access.trialUsed);
  const retry = () => { reload(); void access.retry(); };
  return { visible, checking, failed: loadFailed || (profile !== null && access.error), needsSubscription, concerns, products, retry };
}
