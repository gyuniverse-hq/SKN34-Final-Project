import { useCallback, useEffect, useMemo, useState } from 'react';
import { uuid } from 'expo';
import { apiPost } from '@/lib/api';
import { paletteSwatchKey, pickPalette, placePicksAround, type PaletteInputs, type PickStrategy } from '@/lib/arPalettePicks';
import { ArHistorySession, ArPaletteView, noteArFailure, postArHistory, type RankedArPalette } from '@/lib/arHistory';
import { useAuth } from '@/lib/auth';
import type { ColorSwatch, NearbyDirection } from '@/lib/nearbyColors';
import type { MakeupZone } from '@/types';

interface PaletteContext {
  active: boolean;
  zone: MakeupZone;
  direction: NearbyDirection;
  nearby: readonly ColorSwatch[] | null;
  catalog: readonly ColorSwatch[];
  visibleItems: readonly ColorSwatch[];
  paletteShown: boolean;
  careOpen: boolean;
  scopeKey?: string;
  filterKey?: string;
}

interface NearbyPalette {
  history: ArHistorySession;
  zone: MakeupZone;
  scopeKey: string;
  items: readonly ColorSwatch[];
  strategy: PickStrategy;
  ranked: RankedArPalette | undefined;
  returned?: { anchor: string; filterKey: string };
}

export function useArHistory({ active, zone, direction, nearby, catalog, visibleItems, paletteShown, careOpen,
  scopeKey = '', filterKey = '' }: PaletteContext) {
  const { user } = useAuth();
  const owner = user?.id;
  const session = useMemo(() => active && owner
    ? new ArHistorySession((path, body) => postArHistory(owner, path, body), owner) : null, [active, owner]);
  const [allowed, setAllowed] = useState<{ session: ArHistorySession; recommendations: boolean; serverRanking?: boolean } | null>(null);
  useEffect(() => {
    let current = true;
    if (session && owner) {
      void apiPost<{ enabled: boolean; recommendations: boolean; serverRanking?: boolean }>('/api/me/ar-history/status', {}, { expectedUserId: owner })
        .then(({ enabled, recommendations, serverRanking }) => { if (current) setAllowed(enabled ? { session, recommendations, serverRanking } : null); }).catch(noteArFailure);
    }
    return () => { current = false; };
  }, [session, owner]);
  const history = session === allowed?.session ? session : null;
  const canRecommend = !!history && !!allowed?.recommendations;
  const useServerRanking = canRecommend && !!allowed?.serverRanking;
  const [nearbyPalette, setNearbyPalette] = useState<NearbyPalette | null>(null);
  const savedPalette = canRecommend && nearbyPalette?.history === history
    && nearbyPalette.zone === zone && nearbyPalette.scopeKey === scopeKey
    && (!nearbyPalette.returned || nearbyPalette.returned.filterKey === filterKey) ? nearbyPalette : null;
  if (nearbyPalette && !savedPalette) setNearbyPalette(null);
  const returnAnchorKey = savedPalette?.returned?.anchor;
  const returnAnchor = useMemo(() => returnAnchorKey
    ? catalog.find(item => paletteSwatchKey(item) === returnAnchorKey)
    : undefined, [catalog, returnAnchorKey]);
  const returnedPalette = !nearby && !careOpen && returnAnchor ? savedPalette : null;
  const rankRequest = useMemo(() => useServerRanking && history && !careOpen &&
    (zone === 'lip' || zone === 'blush') && catalog.length
    ? { requestId: uuid.v4(), sessionId: history.id, makeupZone: zone,
      shades: visibleItems.map(({ product, shade }) => ({ productId: product.id, shadeId: shade.id })) }
    : null, [useServerRanking, history, careOpen, zone, catalog.length, visibleItems]);
  const [ranked, setRanked] = useState<{ requestId: string; decision: RankedArPalette | null }>();
  const resolved = ranked?.requestId === rankRequest?.requestId ? ranked : undefined;
  useEffect(() => {
    if (!rankRequest || !owner || !paletteShown || nearby || returnedPalette || resolved) return;
    let current = true;
    void apiPost<RankedArPalette>('/api/me/ar-history/rank', rankRequest, { expectedUserId: owner, timeoutMs: 3000 })
      .then(decision => { if (current) setRanked({ requestId: rankRequest.requestId, decision }); })
      .catch(error => {
        noteArFailure(error);
        if (current) setRanked({ requestId: rankRequest.requestId, decision: null });
      });
    return () => { current = false; };
  }, [rankRequest, owner, paletteShown, nearby, returnedPalette, resolved]);
  const rankedItems = useMemo(() => {
    if (!resolved?.decision) return undefined;
    const swatches = new Map(visibleItems.map(item => [JSON.stringify([item.product.id, item.shade.id]), item]));
    return resolved.decision.candidates.flatMap(candidate => {
      const item = swatches.get(JSON.stringify([candidate.productId, candidate.shadeId]));
      return item ? [item] : [];
    });
  }, [resolved, visibleItems]);
  const rankedView = resolved?.decision && rankedItems?.length === resolved.decision.candidates.length
    ? resolved.decision : undefined;
  const needsRule = !useServerRanking || (!!resolved && !rankedView);
  const paletteScope = canRecommend && needsRule ? history : null;
  const [source, setSource] = useState<{ session: ArHistorySession; zone: MakeupZone; data: PaletteInputs } | null>(null);
  useEffect(() => {
    if (!paletteScope || !owner || (zone !== 'lip' && zone !== 'blush')) return;
    let current = true;
    void apiPost<PaletteInputs>('/api/me/ar-history/palette', { makeupZone: zone }, { expectedUserId: owner })
      .then(data => { if (current) setSource({ session: paletteScope, zone, data }); })
      .catch(noteArFailure);
    return () => { current = false; };
  }, [paletteScope, owner, zone]);
  const inputs = paletteScope && source?.session === paletteScope && source.zone === zone
    ? source.data : null;
  const picks = useMemo(() => inputs && !nearby && !careOpen ? pickPalette(inputs, catalog, visibleItems) : null,
    [inputs, nearby, careOpen, catalog, visibleItems]);
  const firstItems = rankedView ? rankedItems : !rankRequest || resolved ? picks?.items : undefined;
  const firstStrategy = rankedView ? 'rating' : picks?.strategy;
  const { ordered, recommendations } = useMemo(() => {
    if (nearby) return { ordered: nearby, recommendations: undefined };
    if (returnedPalette && returnAnchor && returnAnchorKey) {
      const byKey = new Map(visibleItems.map(item => [paletteSwatchKey(item), item]));
      const anchor = byKey.get(returnAnchorKey) ?? returnAnchor;
      const recommendations = returnedPalette.items.flatMap(item => {
        const key = paletteSwatchKey(item);
        const visible = key === returnAnchorKey ? anchor : byKey.get(key);
        return visible ? [visible] : [];
      });
      return { ordered: placePicksAround(visibleItems, recommendations, anchor), recommendations };
    }
    if (!firstItems?.length) return { ordered: visibleItems, recommendations: undefined };
    const suggested = new Set(firstItems);
    return { ordered: [...firstItems, ...visibleItems.filter(item => !suggested.has(item))], recommendations: firstItems };
  }, [nearby, returnedPalette, returnAnchor, returnAnchorKey, visibleItems, firstItems]);
  const items = nearby ?? recommendations;
  const strategy = nearby ? direction : returnedPalette?.strategy ?? firstStrategy;
  const rankedDecision = nearby ? undefined : returnedPalette ? returnedPalette.ranked : rankedView;
  const view = useMemo(() => canRecommend && history && items && (nearby || items.length) && strategy && paletteShown
    ? new ArPaletteView(history.send, history.id, zone, strategy, items, rankedDecision, returnedPalette ? ordered : undefined) : null,
    [history, canRecommend, items, nearby, zone, strategy, paletteShown, rankedDecision, returnedPalette, ordered]);
  useEffect(() => { if (view) void view.register().catch(noteArFailure); }, [view]);
  const visible = useCallback(({ product, shade }: ColorSwatch) => {
    if (view?.contains(product.id, shade.id)) void view.exposure(product.id, shade.id).save().catch(noteArFailure);
  }, [view]);
  const recommendedItems = useMemo(() => recommendations ? new Set(recommendations) : undefined, [recommendations]);
  const beginNearby = () => {
    const strategy = returnedPalette?.strategy ?? firstStrategy;
    setNearbyPalette(history && recommendations?.length && strategy
      ? { history, zone, scopeKey, items: recommendations, strategy, ranked: rankedDecision }
      : null);
  };
  const returnFromNearby = (anchor: ColorSwatch | undefined) => {
    setNearbyPalette(anchor && savedPalette
      ? { ...savedPalette, returned: { anchor: paletteSwatchKey(anchor), filterKey } }
      : null);
  };
  return { history, view, visible: view ? visible : undefined, ordered, recommendedItems, beginNearby, returnFromNearby };
}
