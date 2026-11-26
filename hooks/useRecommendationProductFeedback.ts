import { useEffect, useRef, useState } from 'react';
import { useAuth } from '@/lib/auth';
import { recommendationContext } from '@/lib/recommendationFeedback';

export function useRecommendationProductFeedback(linkId: string | undefined, productId: string | undefined, loaded: boolean) {
  const { user } = useAuth();
  const context = recommendationContext(linkId, user?.id, productId);
  const viewed = useRef(new Set<string>());
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!loaded || !context || !linkId || viewed.current.has(linkId)) return;
    viewed.current.add(linkId);
    void context.feedback.event(context.item, 'product_view').catch(() => setFailed(true));
  }, [loaded, context, linkId]);
  const prepareCartAdd = () => {
    const cart = context?.feedback.cartAdd(context.item);
    return cart && { source: cart.source, record: () => { void cart.record().catch(() => setFailed(true)); } };
  };
  return { prepareCartAdd, failed };
}
