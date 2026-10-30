import { useQueries } from '@tanstack/react-query';
import { useMemo } from 'react';
import { withDevTryOnFallback } from '@/lib/devCatalog';
import { apiGet } from '@/lib/api';
import { findColorGaps, naverShoppingUrl, type ColorGap, type LookLine, type NearestShade } from '@/lib/colorGaps';
import { useProducts } from '@/lib/queries';
import type { MakeupState, MakeupZone, ProductOffers, ShoppingOffer } from '@/types';

/** What the look screen shows for one color nobody in the shop wears. */
export type ResolvedGap =
  | { kind: 'nearest'; zone: MakeupZone; hex: string; nearest: NearestShade; amount: Extract<ColorGap, { kind: 'nearest' }>['amount'] }
  | { kind: 'checking'; zone: MakeupZone; hex: string }
  | { kind: 'offers'; zone: MakeupZone; hex: string; offers: ShoppingOffer[]; url: string }
  /** Shopping search could not be asked (no key, error): the plain search page is the way. */
  | { kind: 'link'; zone: MakeupZone; hex: string; url: string }
  | { kind: 'soldout'; zone: MakeupZone; hex: string };

/**
 * Catalog first (nearest shade, with how thick to wear it), then Naver Shopping for the color, and
 * sold out when both come up empty. Only the nearest catalog shade can go in the cart.
 */
export function useLookColorGaps(makeup: MakeupState, lines: LookLine[]): ResolvedGap[] {
  const catalog = useProducts();
  const tryOn = useMemo(
    () => withDevTryOnFallback((catalog.data ?? []).filter((p) => p.makeupZone), __DEV__),
    [catalog.data]
  );
  const gaps = useMemo(() => findColorGaps(makeup, lines, tryOn), [makeup, lines, tryOn]);
  const searches = gaps.filter((g): g is Extract<ColorGap, { kind: 'search' }> => g.kind === 'search');
  const results = useQueries({
    queries: searches.map((g) => ({
      queryKey: ['offer-search', g.query],
      queryFn: () => apiGet<ProductOffers>(`/api/offers/search?q=${encodeURIComponent(g.query)}`),
      staleTime: 30 * 60 * 1000,
      retry: 1,
    })),
  });

  return useMemo(() => {
    let s = 0;
    return gaps.map((g): ResolvedGap => {
      if (g.kind === 'nearest') return g;
      const result = results[s++];
      const url = naverShoppingUrl(g.query);
      if (!result || result.isPending) return { kind: 'checking', zone: g.zone, hex: g.hex };
      if (result.isError || !result.data.configured) return { kind: 'link', zone: g.zone, hex: g.hex, url };
      if (result.data.offers.length === 0) return { kind: 'soldout', zone: g.zone, hex: g.hex };
      return { kind: 'offers', zone: g.zone, hex: g.hex, offers: result.data.offers.slice(0, 3), url };
    });
  }, [gaps, results]);
}
