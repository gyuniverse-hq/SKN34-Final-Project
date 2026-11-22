import { useCallback, useMemo, useRef, type ComponentRef } from 'react';
import { AppState, type View } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { halfVisible, RecommendationFeedback, recommendationLink, type FeedbackItem } from '@/lib/recommendationFeedback';
import { productHref } from '@/lib/routes';
import type { HybridResponse } from '@/types/skincare';

/** Measure the actual clipped scroll viewport before recording a card impression. */
export function useRecommendationCardFeedback(
  history: HybridResponse['history'], items: readonly FeedbackItem[] | undefined,
  owner: string | undefined, enabled = true, topInset = 0,
) {
  const viewportRef = useRef<ComponentRef<typeof View>>(null);
  const cards = useRef(new Map<string, ComponentRef<typeof View>>());
  const requestId = history?.requestId;
  const sessionId = history?.sessionId;
  const feedback = useMemo(() => requestId && sessionId && owner ? new RecommendationFeedback(owner, sessionId) : undefined,
    [requestId, sessionId, owner]);
  const refresh = useRef(() => {});
  useFocusEffect(useCallback(() => {
    if (!feedback || !items || !enabled) return;
    let mounted = true;
    let generation = 0;
    let active = AppState.currentState !== 'background' && AppState.currentState !== 'inactive';
    const since = new Map<string, number>();
    const sent = new Set<string>();
    const measure = () => {
      const epoch = ++generation;
      if (!active || !mounted) return;
      viewportRef.current?.measureInWindow((x, y, width, height) => {
        if (!mounted || !active || epoch !== generation) return;
        for (const item of items) {
          const id = item.candidateId;
          if (!id || sent.has(id)) continue;
          cards.current.get(id)?.measureInWindow((cx, cy, cw, ch) => {
            if (!mounted || !active || epoch !== generation) return;
            if (!halfVisible({ x: cx, y: cy, width: cw, height: ch },
              { x, y: y + topInset, width, height: Math.max(0, height - topInset) })) {
              since.delete(id); return;
            }
            const now = Date.now();
            if (!since.has(id)) since.set(id, now);
            if (now - since.get(id)! < 500) return;
            sent.add(id);
            void feedback.impression(item).catch(() => {});
          });
        }
      });
    };
    const subscription = AppState.addEventListener('change', state => {
      active = state === 'active'; since.clear(); generation++; measure();
    });
    refresh.current = measure;
    const timer = setInterval(measure, 200);
    measure();
    return () => { mounted = false; generation++; clearInterval(timer); subscription.remove(); refresh.current = () => {}; };
  }, [feedback, items, enabled, topInset]));
  const setCard = (item: FeedbackItem, node: ComponentRef<typeof View> | null) => {
    if (!item.candidateId) return;
    if (node) cards.current.set(item.candidateId, node);
    else cards.current.delete(item.candidateId);
  };
  const href = (item: FeedbackItem) => {
    if (!feedback || !item.candidateId) return productHref(item.productId);
    // A tap confirms exposure even if the product detail fails to load.
    void feedback.impression(item, true).catch(() => {});
    return productHref(item.productId, undefined, recommendationLink(feedback, item));
  };
  return { viewportRef, setCard, refresh: () => refresh.current(), href };
}
