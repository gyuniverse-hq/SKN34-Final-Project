import { useCallback, useMemo, useRef, useState, type ComponentRef } from 'react';
import { AppState, type View } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { halfVisible, RecommendationFeedback, recommendationLink } from '@/lib/recommendationFeedback';
import { productHref } from '@/lib/routes';
import type { ComparisonProduct, RecommendationComparisonResult } from '@/types/recommendationComparison';

/** Measure the actual clipped scroll viewport; fetching/mounting a card is not an impression. */
export function useRecommendationFeedback(result: RecommendationComparisonResult | undefined, owner: string | undefined) {
  const viewportRef = useRef<ComponentRef<typeof View>>(null);
  const cards = useRef(new Map<string, ComponentRef<typeof View>>());
  const [failedView, setFailedView] = useState<string>();
  const requestId = result?.history?.requestId;
  const sessionId = result?.history?.sessionId;
  const feedback = useMemo(() => requestId && sessionId && owner ? new RecommendationFeedback(owner, sessionId) : undefined,
    [requestId, sessionId, owner]);
  const refresh = useRef(() => {});
  const items = result?.v2.matches;
  useFocusEffect(useCallback(() => {
    if (!feedback || !items) return;
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
            if (!halfVisible({ x: cx, y: cy, width: cw, height: ch }, { x, y, width, height })) {
              since.delete(id); return;
            }
            const now = Date.now();
            if (!since.has(id)) since.set(id, now);
            if (now - since.get(id)! < 500) return;
            sent.add(id);
            void feedback.impression(item).catch(() => { if (mounted) setFailedView(feedback.viewId); });
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
  }, [feedback, items]));
  const setCard = (item: ComparisonProduct, node: ComponentRef<typeof View> | null) => {
    if (!item.candidateId) return;
    if (node) cards.current.set(item.candidateId, node);
    else cards.current.delete(item.candidateId);
  };
  const href = (item: ComparisonProduct) => {
    const recommendation = feedback && item.candidateId ? recommendationLink(feedback, item) : undefined;
    // Navigation is immediate; the detail action waits for its real impression acknowledgement.
    return productHref(item.productId, undefined, recommendation);
  };
  return { viewportRef, setCard, refresh: () => refresh.current(), href, failed: !!feedback && failedView === feedback.viewId };
}
