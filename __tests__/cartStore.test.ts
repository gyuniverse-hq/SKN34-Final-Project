import { cartLineKey, MAX_QUANTITY, selectCartCount, useCartStore } from '@/store/cartStore';

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
});
