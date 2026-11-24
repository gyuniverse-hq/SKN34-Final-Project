import { useEffect, useLayoutEffect, type ComponentRef } from 'react';
import { AppState, type View } from 'react-native';
import renderer, { act } from 'react-test-renderer';
import { useCartRecommendations } from '@/hooks/useCartRecommendations';
import { useVisibleCards } from '@/hooks/useRecommendationFeedback';
import { apiPost } from '@/lib/api';
import { clearCartArRanks, rememberCartArRank } from '@/lib/cartRecommendations';
import type { Rect } from '@/lib/recommendationFeedback';
import { useCartStore } from '@/store/cartStore';
import type { CartRecommendationCandidate, Product } from '@/types';

jest.mock('@/lib/api', () => ({ apiPost: jest.fn() }));
jest.mock('@/lib/queries', () => ({ useProductsByIds: () => ({ data: mockProducts }) }));
jest.mock('expo-router', () => ({
  useFocusEffect: (effect: () => void) => jest.requireActual('react').useEffect(effect, [effect]),
}));

const mockProducts: Product[] = [{
  id: 'blush', brand: 'Brand', name: 'Pink Blush', nameKo: '핑크 블러셔', category: 'cheek', makeupZone: 'blush',
  texture: 'matte', priceKRW: 9000, volume: '3g', description: '', tags: [], keyIngredients: [],
  imageUrl: '', searchKeyword: '', shades: [{ id: 'pink', name: 'Pink', hex: '#C26471' }],
}];
const candidate: CartRecommendationCandidate = {
  candidateId: 'card', productId: 'blush', shadeId: 'pink', makeupZone: 'blush',
  position: 1, originalRank: 4, policyVersion: 'ar1:-:-:rule',
};
const path = '/api/me/cart-recommendations';
const post = jest.mocked(apiPost);
let result: ReturnType<typeof useCartRecommendations>;

function Screen({ owner }: { owner: string }) {
  const items = useCartStore(state => state.items);
  const recommendation = useCartRecommendations(owner, items, items.slice(0, 1).map(item => ({
    key: item.productId, item, product: mockProducts[0], availability: 'available', lineTotal: 1000,
  })), true);
  useEffect(() => { result = recommendation; }, [recommendation]);
  return null;
}

beforeEach(() => {
  post.mockReset();
  clearCartArRanks();
  useCartStore.setState({ items: [{ productId: 'lip', shadeId: 'rose', quantity: 1 }], pendingPayment: null });
});

it('keeps one visit while the basket changes and attributes a single exact-shade addition', async () => {
  rememberCartArRank('owner', 'lip', 'rank-lip');
  post.mockImplementation(async (endpoint, body) => {
    if (endpoint === path) return { cartVisitId: (body as { cartVisitId: string }).cartVisitId, candidates: [candidate] };
    if (endpoint.endsWith('/impressions')) return { impressionId: 'canonical-impression' };
    return { ok: true };
  });
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<Screen owner="owner" />); });
  const visitId = result.cartVisitId;
  expect(result.cards.map(card => card.shade.id)).toEqual(['pink']);
  expect(post).toHaveBeenCalledWith(path, {
    cartVisitId: visitId, items: [{ productId: 'lip', shadeId: 'rose' }], arRequestIds: { lip: 'rank-lip' },
  }, expect.objectContaining({ expectedUserId: 'owner' }));
  await act(async () => { result.add(candidate); result.add(candidate); });
  const added = useCartStore.getState().items[1];
  expect(added).toMatchObject({ productId: 'blush', shadeId: 'pink', quantity: 1 });
  expect(post.mock.calls.map(([endpoint]) => endpoint)).toEqual([path, path + '/impressions', path + '/cart-adds']);
  expect(post).toHaveBeenCalledWith(path + '/cart-adds', {
    eventId: added.cartRecommendationSources?.[0]?.eventId, impressionId: 'canonical-impression',
  }, expect.objectContaining({ expectedUserId: 'owner' }));
  expect(result.cartVisitId).toBe(visitId);
  await act(async () => { screen.unmount(); });
});

it('gives an eligible control visit a checkout ID and clears it on an account change', async () => {
  rememberCartArRank('owner', 'lip', 'rank-lip');
  post.mockImplementation(async (_endpoint, body, options) => options?.expectedUserId === 'owner'
    ? { cartVisitId: (body as { cartVisitId: string }).cartVisitId, candidates: [] } : null);
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<Screen owner="owner" />); });
  expect(result.cards).toEqual([]);
  expect(result.cartVisitId).toEqual(expect.any(String));
  await act(async () => { screen.update(<Screen owner="different-owner" />); });
  expect(result.cartVisitId).toBeUndefined();
  expect(post).toHaveBeenLastCalledWith(path, {
    cartVisitId: expect.any(String), items: [{ productId: 'lip', shadeId: 'rose' }], arRequestIds: undefined,
  }, expect.objectContaining({ expectedUserId: 'different-owner' }));
  await act(async () => { screen.unmount(); });
});

it('counts a card only after half of it stays visible across both scroll viewports', async () => {
  const report = jest.fn();
  const ids = ['card'];
  const rects: Record<string, Rect> = {
    list: { x: 0, y: 0, width: 200, height: 120 },
    shelf: { x: 20, y: 70, width: 100, height: 80 },
    card: { x: 40, y: 100, width: 80, height: 80 },
  };
  const measuredView = (name: string) => ({
    measureInWindow: (measure: (x: number, y: number, width: number, height: number) => void) => {
      const { x, y, width, height } = rects[name];
      measure(x, y, width, height);
    },
  }) as ComponentRef<typeof View>;
  let refresh!: () => void;
  function MeasurementScreen() {
    const { viewportRef, clipRef, setCard, refresh: refreshMeasurement } = useVisibleCards(ids, report, true);
    useLayoutEffect(() => {
      viewportRef.current = measuredView('list');
      clipRef.current = measuredView('shelf');
      setCard('card', measuredView('card'));
      refresh = refreshMeasurement;
    }, [viewportRef, clipRef, refreshMeasurement, setCard]);
    return null;
  }
  const initialAppState = AppState.currentState;
  AppState.currentState = 'active';
  jest.useFakeTimers();
  let screen: renderer.ReactTestRenderer | undefined;
  try {
    await act(async () => { screen = renderer.create(<MeasurementScreen />); });
    act(() => { jest.advanceTimersByTime(600); });
    expect(report).not.toHaveBeenCalled();
    rects.card.y = 80;
    act(() => { refresh(); jest.advanceTimersByTime(400); });
    expect(report).not.toHaveBeenCalled();
    act(() => { jest.advanceTimersByTime(200); });
    expect(report).toHaveBeenCalledTimes(1);
    expect(report).toHaveBeenCalledWith('card');
  } finally {
    if (screen) await act(async () => { screen?.unmount(); });
    AppState.currentState = initialAppState;
    jest.useRealTimers();
  }
});
