import { useCallback, useMemo, useRef, type ComponentRef } from 'react';
import { AppState, type View } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { halfVisible, RecommendationFeedback, recommendationLink, type FeedbackItem, type Rect } from '@/lib/recommendationFeedback';
import { productHref } from '@/lib/routes';
import type { HybridResponse } from '@/types/skincare';

/** Measure a card against the screen's scroll viewport and its optional nested viewport. */
export function useVisibleCards(ids: readonly string[], onImpression: (id: string) => void, enabled: boolean, topInset = 0) {
  const viewportRef = useRef<ComponentRef<typeof View>>(null);
  const clipRef = useRef<ComponentRef<typeof View>>(null);
  const cards = useRef(new Map<string, ComponentRef<typeof View>>());
  const refresh = useRef(() => {});
  useFocusEffect(useCallback(() => {
    if (!enabled || !ids.length) return;
    let mounted = true;
    let generation = 0;
    let active = AppState.currentState !== 'background' && AppState.currentState !== 'inactive';
    const since = new Map<string, number>();
    const sent = new Set<string>();
    const measure = () => {
      const epoch = ++generation;
      if (!active || !mounted) return;
      viewportRef.current?.measureInWindow((x, y, width, height) => {
        const measureCards = (viewport: Rect) => {
          if (!mounted || !active || epoch !== generation) return;
          for (const id of ids) {
            if (sent.has(id)) continue;
            const card = cards.current.get(id);
            if (!card) { since.delete(id); continue; }
            card.measureInWindow((cx, cy, cw, ch) => {
              if (!mounted || !active || epoch !== generation) return;
              if (!halfVisible({ x: cx, y: cy, width: cw, height: ch }, viewport)) {
                since.delete(id); return;
              }
              const now = Date.now();
              if (!since.has(id)) since.set(id, now);
              if (now - since.get(id)! < 500) return;
              sent.add(id);
              onImpression(id);
            });
          }
        };
        const top = y + topInset;
        const nested = clipRef.current;
        if (!nested) {
          measureCards({ x, y: top, width, height: Math.max(0, height - topInset) });
          return;
        }
        nested.measureInWindow((nx, ny, nw, nh) => {
          const left = Math.max(x, nx);
          const upper = Math.max(top, ny);
          measureCards({ x: left, y: upper, width: Math.max(0, Math.min(x + width, nx + nw) - left),
            height: Math.max(0, Math.min(y + height, ny + nh) - upper) });
        });
      });
    };
    const subscription = AppState.addEventListener('change', state => {
      active = state === 'active'; since.clear(); generation++; measure();
    });
    refresh.current = measure;
    const timer = setInterval(measure, 200);
    measure();
    return () => { mounted = false; generation++; clearInterval(timer); subscription.remove(); refresh.current = () => {}; };
  }, [ids, onImpression, enabled, topInset]));
  const setCard = (id: string, node: ComponentRef<typeof View> | null) => {
    if (node) cards.current.set(id, node);
    else cards.current.delete(id);
  };
  return { viewportRef, clipRef, setCard, refresh: () => refresh.current() };
}

export function useRecommendationCardFeedback(
  history: HybridResponse['history'], items: readonly FeedbackItem[] | undefined,
  owner: string | undefined, enabled = true, topInset = 0,
) {
  const requestId = history?.requestId;
  const sessionId = history?.sessionId;
  const feedback = useMemo(() => requestId && sessionId && owner ? new RecommendationFeedback(owner, sessionId) : undefined,
    [requestId, sessionId, owner]);
  const byId = useMemo(() => new Map(items?.flatMap(item => item.candidateId ? [[item.candidateId, item] as const] : [])), [items]);
  const ids = useMemo(() => [...byId.keys()], [byId]);
  const onImpression = useCallback((id: string) => {
    const item = byId.get(id);
    if (item) void feedback?.impression(item).catch(() => {});
  }, [feedback, byId]);
  const visibility = useVisibleCards(ids, onImpression, !!feedback && enabled, topInset);
  const href = (item: FeedbackItem) => {
    if (!feedback || !item.candidateId) return productHref(item.productId);
    // A tap confirms exposure even if the product detail fails to load.
    void feedback.impression(item, true).catch(() => {});
    return productHref(item.productId, undefined, recommendationLink(feedback, item));
  };
  return { ...visibility, setCard: (item: FeedbackItem, node: ComponentRef<typeof View> | null) => {
    if (item.candidateId) visibility.setCard(item.candidateId, node);
  }, href };
}
