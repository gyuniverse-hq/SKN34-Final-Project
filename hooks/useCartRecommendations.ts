import { uuid } from 'expo';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { CartLine } from '@/hooks/useCartLines';
import { trackCartEvent } from '@/lib/cartAttribution';
import { CartRecommendationFeedback, requestCartRecommendations } from '@/lib/cartRecommendations';
import { resolveShade } from '@/lib/catalog';
import { useProductsByIds } from '@/lib/queries';
import { useCartStore } from '@/store/cartStore';
import type { CartItem, CartRecommendationCandidate, CartRecommendations } from '@/types';

type Visit = { owner: string; id: string; promise: Promise<CartRecommendations | null> };

export function useCartRecommendations(owner: string | undefined, items: CartItem[], lines: CartLine[], ready: boolean) {
  const attempt = useRef<Visit | undefined>(undefined);
  const [visit, setVisit] = useState<Visit>();
  const [resolved, setResolved] = useState<{ visit: Visit; response: CartRecommendations | null }>();
  useEffect(() => {
    if (!owner || !items.length || attempt.current?.owner !== owner) {
      attempt.current = undefined;
      setVisit(undefined);
      setResolved(undefined);
    }
    if (!owner || !ready || !lines.length || items.length > 30) return;
    if (!attempt.current) {
      const id = uuid.v4();
      const promise = requestCartRecommendations(owner, id, items.map(({ productId, shadeId }) => ({
        productId, shadeId,
      }))).catch(() => null);
      trackCartEvent(id, promise);
      attempt.current = { owner, id, promise };
      setVisit(attempt.current);
    }
    const current = attempt.current;
    let active = true;
    void current.promise.then(response => {
      if (active) setResolved(previous => previous?.visit === current ? previous : { visit: current, response });
    });
    return () => { active = false; };
  }, [owner, items, lines.length, ready]);

  const current = items.length && visit?.owner === owner ? visit : undefined;
  const decision = current && current === resolved?.visit ? resolved.response : undefined;
  const cartVisitId = current && decision !== null ? current.id : undefined;
  const feedback = useMemo(() => owner && decision?.candidates.length
    ? new CartRecommendationFeedback(owner, decision.cartVisitId) : undefined, [owner, decision]);
  const products = useProductsByIds(decision?.candidates.map(card => card.productId) ?? []);
  const cards = useMemo(() => {
    const byId = new Map(products.data?.map(product => [product.id, product]));
    return decision?.candidates.flatMap(candidate => {
      const product = byId.get(candidate.productId);
      const { shade } = resolveShade(product, candidate.shadeId);
      return product?.makeupZone === candidate.makeupZone && product.priceKRW > 0 && shade
        ? [{ candidate, product, shade }] : [];
    }) ?? [];
  }, [decision, products.data]);
  const ids = useMemo(() => cards.map(card => card.candidate.candidateId), [cards]);
  const onImpression = useCallback((id: string) => { void feedback?.impression(id).catch(() => {}); }, [feedback]);
  const interact = (candidate: CartRecommendationCandidate) => {
    void feedback?.impression(candidate.candidateId, true).catch(() => {});
  };
  const add = (candidate: CartRecommendationCandidate) => {
    if (!feedback) return;
    const cart = useCartStore.getState();
    if (cart.items.some(item => item.productId === candidate.productId)) return;
    const eventId = uuid.v4();
    cart.add({
      productId: candidate.productId, shadeId: candidate.shadeId,
      cartRecommendationSources: [{ ownerId: feedback.owner, eventId }],
    });
    trackCartEvent(eventId, feedback.add(candidate.candidateId, eventId));
  };
  return { cartVisitId, cards, ids, onImpression, interact, add };
}
