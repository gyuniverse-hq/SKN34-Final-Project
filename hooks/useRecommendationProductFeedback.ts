import { useCallback, useEffect, useRef, useState } from 'react';
import { useAuth } from '@/lib/auth';
import { recommendationContext } from '@/lib/recommendationFeedback';

export function useRecommendationProductFeedback(linkId: string | undefined, productId: string | undefined, loaded: boolean) {
  const { user } = useAuth();
  const context = recommendationContext(linkId, user?.id, productId);
  const viewed = useRef(new Set<string>());
  const [failed, setFailed] = useState(false);
  const record = useCallback((type: 'product_view' | 'cart_add' | 'outbound_click') => {
    if (context) void context.feedback.event(context.item, type).catch(() => setFailed(true));
  }, [context]);
  useEffect(() => {
    if (!loaded || !context || !linkId || viewed.current.has(linkId)) return;
    viewed.current.add(linkId);
    record('product_view');
  }, [loaded, context, linkId, record]);
  return { record, failed };
}
