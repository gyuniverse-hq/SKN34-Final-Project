import { useEffect, useMemo } from 'react';
import { useProducts } from '@/lib/queries';
import { suggestConcerns } from '@/lib/skinFilters';
import { useSkinProfileStore } from '@/store/skinProfileStore';

/** Products for the saved on-device skin result; skincare picks until there is one. */
export function useSkinMatchedProducts() {
  const profile = useSkinProfileStore((s) => s.profile);
  const hydrate = useSkinProfileStore((s) => s.hydrate);

  useEffect(() => {
    void hydrate().catch(() => {});
  }, [hydrate]);

  const concerns = useMemo(() => suggestConcerns(profile), [profile]);
  const products = useProducts(concerns.length > 0 ? { concerns } : { category: 'skincare' });
  return { hasProfile: profile !== null, concerns, products };
}
