import { useMemo, useState } from 'react';
import { findNearbyColors, indexNearbyColors, supportsNearby, type ColorSwatch, type NearbyDirection } from '@/lib/nearbyColors';
import type { MakeupZone, Product, Texture } from '@/types';

interface Selection { productId: string; shadeId: string }
interface Session {
  zone: MakeupZone;
  scopeKey: string;
  anchor: Selection;
  history: Selection[];
  direction: NearbyDirection;
}
const selectionOf = ({ product, shade }: ColorSwatch): Selection => ({ productId: product.id, shadeId: shade.id });
const isSelection = (swatch: ColorSwatch, selection: Selection) =>
  swatch.product.id === selection.productId && swatch.shade.id === selection.shadeId;

/** Candidate previews do not move the anchor. Only enter/rebase/back changes it. */
export function useNearbyExploration(products: Product[], zone: MakeupZone, selected: ColorSwatch | undefined, texture: Texture | null, scopeKey: string) {
  const index = useMemo(() => indexNearbyColors(products), [products]);
  const [session, setSession] = useState<Session | null>(null);
  const current = selected && index.find((item) => isSelection(item, selectionOf(selected)) && item.product.makeupZone === zone);
  const anchor = session && session.zone === zone && session.scopeKey === scopeKey
    ? index.find((item) => isSelection(item, session.anchor) && item.product.makeupZone === zone) : undefined;
  // Reset on category, route/recipe or catalog removal, before any stale results render.
  if (session && !anchor) setSession(null);
  const active = !!anchor;
  const direction = session?.direction ?? 'similar';
  const groups = useMemo(() => findNearbyColors(index, anchor, texture), [index, anchor, texture]);
  const canRebase = !!current && !!anchor && !isSelection(current, selectionOf(anchor));
  return {
    supported: supportsNearby(zone), active, anchor, direction, groups,
    canEnter: !!current, canRebase, canGoBack: !!session?.history.length,
    enter: () => {
      if (current) setSession({ zone, scopeKey, anchor: selectionOf(current), history: [], direction: 'similar' });
    },
    leave: () => setSession(null),
    setDirection: (next: NearbyDirection) => setSession((prev) => prev ? { ...prev, direction: next } : prev),
    rebase: () => {
      if (current && canRebase) setSession((prev) => prev ? {
        ...prev, anchor: selectionOf(current), history: [...prev.history, prev.anchor],
      } : prev);
    },
    back: () => setSession((prev) => prev?.history.length ? {
      ...prev, anchor: prev.history[prev.history.length - 1], history: prev.history.slice(0, -1),
    } : prev),
  };
}
