import { cartLineKey, MAX_QUANTITY, selectCartCount, useCartStore } from '@/store/cartStore';
import { arCartEventIds } from '@/lib/arHistory';

beforeEach(() => useCartStore.getState().clear());

describe('cartStore', () => {
  it('merges identical product + shade lines', () => {
    const { add } = useCartStore.getState();
    add({ productId: 'a', shadeId: '01' });
    add({ productId: 'a', shadeId: '01' });
    add({ productId: 'a', shadeId: '02' });
    const items = useCartStore.getState().items;
    expect(items).toHaveLength(2);
    expect(items[0].quantity).toBe(2);
    expect(selectCartCount(useCartStore.getState())).toBe(3);
  });

  it('adds a full look set in one call', () => {
    useCartStore.getState().addMany([
      { productId: 'a', shadeId: '01', addedFromLookId: 'look' },
      { productId: 'b' },
    ]);
    expect(useCartStore.getState().items.map((i) => i.productId)).toEqual(['a', 'b']);
  });

  it('caps quantity and removes at zero', () => {
    const { add, setQuantity } = useCartStore.getState();
    add({ productId: 'a' }, 50);
    expect(useCartStore.getState().items[0].quantity).toBe(MAX_QUANTITY);
    setQuantity(cartLineKey({ productId: 'a' }), 0);
    expect(useCartStore.getState().items).toHaveLength(0);
  });

  it('keeps AR sources only for the remaining units and the matching account', () => {
    const { add, setQuantity } = useCartStore.getState();
    const item = { productId: 'a', shadeId: '01' };
    const key = cartLineKey(item);
    const sources = () => arCartEventIds(useCartStore.getState().items[0], 'owner');
    add(item);
    add({ ...item, arCartSources: [{ ownerId: 'owner', eventId: 'first' }] });
    add({ ...item, arCartSources: [{ ownerId: 'other', eventId: 'second' }] });
    add({ ...item, arCartSources: [{ ownerId: 'owner', eventId: 'third' }] });
    expect(sources()).toEqual(['first', 'third']);
    setQuantity(key, 2);
    expect(sources()).toEqual(['first']);
    setQuantity(key, 1);
    setQuantity(key, 4);
    expect(sources()).toEqual([]);
  });

  it('removes only unchanged lines from a confirmed order, preserving new or edited items', () => {
    const store = useCartStore.getState();
    store.add({ productId: 'paid', shadeId: '01' }, 2);
    store.add({ productId: 'edited', shadeId: '02' });
    store.setPendingPayment({ orderId: 'order-1', userId: 'user-1', items: [...useCartStore.getState().items] });
    store.add({ productId: 'edited', shadeId: '02' });
    store.add({ productId: 'new' });
    store.completePayment('wrong-order');
    expect(useCartStore.getState().items).toHaveLength(3);
    store.completePayment('order-1');
    expect(useCartStore.getState().items.map((item) => [item.productId, item.quantity])).toEqual([['edited', 2], ['new', 1]]);
    expect(useCartStore.getState().pendingPayment).toBeNull();
  });

  it('keeps pending payment when clearing the cart, but deletes it when all data is reset', () => {
    const store = useCartStore.getState();
    store.setPendingPayment({ orderId: 'order-2', userId: 'user-1', items: [] });
    store.clear();
    expect(useCartStore.getState().pendingPayment?.orderId).toBe('order-2');
    store.reset();
    expect(useCartStore.getState().pendingPayment).toBeNull();
  });

  it('clears a pending payment without changing cart items', () => {
    const store = useCartStore.getState();
    store.add({ productId: 'a' });
    store.setPendingPayment({
      orderId: 'order-3',
      userId: 'user-1',
      items: [...useCartStore.getState().items],
      checkoutUrl: 'https://example.com/pay',
    });
    store.clearPendingPayment();
    expect(useCartStore.getState().pendingPayment).toBeNull();
    expect(useCartStore.getState().items).toHaveLength(1);
  });
});
