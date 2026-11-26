import React from 'react';
import renderer, { act } from 'react-test-renderer';
import * as WebBrowser from 'expo-web-browser';
import CheckoutScreen from '@/app/checkout';
import { Button } from '@/components/ui/Button';
import { ApiError, apiGet, apiPost } from '@/lib/api';
import { useCartStore } from '@/store/cartStore';
import type { CartItem } from '@/types';

jest.mock('@expo/vector-icons/Ionicons', () => 'Ionicons');
jest.mock('@/components/ui/StateViews', () => ({ EmptyState: 'EmptyState', LoadingState: 'LoadingState' }));
const mockWallet = { data: { coupons: [] as { id: string; status: string }[] }, refetch: jest.fn() };
jest.mock('@/hooks/useRewards', () => ({ useRewards: () => mockWallet }));
let mockSubtotal = 1000;
jest.mock('@/components/ui/ProductImage', () => ({ ProductImage: 'ProductImage' }));
const mockSearchParams: { cartVisitId?: string; productId?: string; shadeId?: string } = {};
let mockUser: { id: string } | null = { id: 'user-1' };
const mockReplace = jest.fn();
jest.mock('expo-router', () => ({
  useRouter: () => ({ replace: mockReplace }),
  useLocalSearchParams: () => mockSearchParams,
}));
jest.mock('expo-web-browser', () => ({ openAuthSessionAsync: jest.fn() }));
jest.mock('@/lib/auth', () => ({ useAuth: () => ({ user: mockUser, ready: true }) }));
jest.mock('@/lib/api', () => {
  class ApiError extends Error {
    status: number;
    code?: string;
    constructor(message: string, status: number, code?: string) {
      super(message);
      this.name = 'ApiError';
      this.status = status;
      this.code = code;
    }
  }
  return { ApiError, API_BASE_URL: 'http://localhost:8080', apiGet: jest.fn(), apiPost: jest.fn() };
});
jest.mock('@/lib/i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }));
jest.mock('@/hooks/useCartLines', () => {
  const { useCartStore } = jest.requireActual('@/store/cartStore');
  return {
    useCartLines: (orderItems?: CartItem[]) => ({
      lines: (orderItems ?? [useCartStore.getState().items[0] ?? { productId: 'p', shadeId: 's', quantity: 1 }]).map((item) => ({
        key: `${item.productId}::${item.shadeId}`, item,
        product: { id: item.productId, brand: 'B', name: 'P', category: 'lip', imageUrl: 'https://example.com/p.jpg' },
        shade: { id: item.shadeId, name: 'S' }, lineTotal: 1000,
      })),
      total: mockSubtotal,
      query: { isPending: false },
    }),
  };
});

const browser = jest.mocked(WebBrowser.openAuthSessionAsync);
const get = jest.mocked(apiGet);
const post = jest.mocked(apiPost);
let mounted: renderer.ReactTestRenderer | undefined;

beforeEach(() => {
  jest.clearAllMocks();
  mockWallet.data.coupons = [];
  mockSubtotal = 1000;
  delete mockSearchParams.cartVisitId;
  delete mockSearchParams.productId;
  delete mockSearchParams.shadeId;
  mockUser = { id: 'user-1' };
  useCartStore.setState({ items: [{ productId: 'p', shadeId: 's', quantity: 1 }], pendingPayment: null });
  post.mockResolvedValue({ orderId: 'order-1', checkoutUrl: 'https://example.com/pay', amount: 1000 });
});

afterEach(async () => {
  if (mounted) await act(async () => { mounted!.unmount(); });
  mounted = undefined;
});

async function start() {
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<CheckoutScreen />); });
  mounted = screen;
  await act(async () => { await screen.root.findByType(Button).props.onPress(); });
  return screen;
}

it('clears paid items only after the server confirms the order', async () => {
  browser.mockResolvedValue({ type: 'success', url: 'kbeautyar://payment-result?orderId=order-1' });
  get.mockResolvedValue({ orderId: 'order-1', status: 'paid' });
  const screen = await start();
  expect(get).toHaveBeenCalledWith('/api/payments/orders/order-1', { expectedUserId: 'user-1' });
  expect(useCartStore.getState().items).toHaveLength(0);
  expect(JSON.stringify(screen.toJSON())).toContain('checkout.paid');
  expect(JSON.stringify(screen.toJSON())).toContain('checkout.goShop');
});

it('buys one exact shade directly and preserves identical and unrelated cart items', async () => {
  mockSearchParams.productId = 'p';
  mockSearchParams.shadeId = 's';
  mockSearchParams.cartVisitId = '088d42bd-bc31-4677-92a8-6d7fda10f175';
  const cart = [{ productId: 'p', shadeId: 's', quantity: 1 }, { productId: 'other', quantity: 2 }];
  useCartStore.setState({ items: cart });
  browser.mockResolvedValue({ type: 'success', url: 'kbeautyar://payment-result?orderId=order-1' });
  get.mockResolvedValue({ orderId: 'order-1', status: 'paid' });
  await start();
  expect(post).toHaveBeenCalledWith('/api/payments/orders', {
    lines: [{ productId: 'p', shadeId: 's', quantity: 1 }],
  }, { expectedUserId: 'user-1' });
  expect(useCartStore.getState().items).toEqual(cart);
});

it('carries the requested shade through sign-in and rejects incomplete direct orders', async () => {
  mockUser = null;
  mockSearchParams.productId = 'p';
  mockSearchParams.shadeId = 'other-shade';
  await act(async () => { mounted = renderer.create(<CheckoutScreen />); });
  expect(mockReplace).toHaveBeenCalledWith({
    pathname: '/login', params: { returnTo: 'checkout', productId: 'p', shadeId: 'other-shade' },
  });
  mockReplace.mockClear();
  delete mockSearchParams.shadeId;
  await act(async () => { mounted!.update(<CheckoutScreen />); });
  expect(JSON.stringify(mounted!.toJSON())).toContain('lookPreview.purchaseUnavailable');
  expect(mockReplace).not.toHaveBeenCalled();
  expect(post).not.toHaveBeenCalled();
});

it('sends the current account’s AR and skincare origins in their own order fields', async () => {
  useCartStore.setState({ items: [{ productId: 'p', shadeId: 's', quantity: 2, arCartSources: [
    { ownerId: 'user-1', eventId: 'my-event' }, { ownerId: 'user-2', eventId: 'other-event' },
  ], skincareCartSources: [
    { ownerId: 'user-2', eventId: 'other-skincare' }, { ownerId: 'user-1', eventId: 'my-skincare' },
  ] }] });
  browser.mockResolvedValue({ type: 'cancel' as WebBrowser.WebBrowserResultType.CANCEL });
  get.mockResolvedValue({ orderId: 'order-1', status: 'pending' });
  await start();
  expect(post).toHaveBeenCalledWith('/api/payments/orders', {
    lines: [{ productId: 'p', shadeId: 's', quantity: 2,
      arCartEventIds: ['my-event'], skincareCartEventIds: ['my-skincare'] }],
  }, { expectedUserId: 'user-1' });
});

it('keeps the cart and pending order when the payment window closes', async () => {
  browser.mockResolvedValue({ type: 'cancel' as WebBrowser.WebBrowserResultType.CANCEL });
  get.mockResolvedValue({ orderId: 'order-1', status: 'pending' });
  const screen = await start();
  expect(useCartStore.getState().items).toHaveLength(1);
  expect(useCartStore.getState().pendingPayment).toEqual(expect.objectContaining({
    orderId: 'order-1',
    checkoutUrl: 'https://example.com/pay',
  }));
  expect(JSON.stringify(screen.toJSON())).toContain('checkout.closed');
  get.mockResolvedValue({ orderId: 'order-1', status: 'paid' });
  const check = screen.root.findAllByType(Button).find((button) => button.props.label === 'checkout.checkStatus');
  await act(async () => { await check!.props.onPress(); });
  expect(useCartStore.getState().items).toHaveLength(0);
  expect(JSON.stringify(screen.toJSON())).toContain('checkout.paid');
});

it.each([false, true])('links checkout to a cart visit with recommendation sources: %s', async (hasSource) => {
  mockSearchParams.cartVisitId = '088d42bd-bc31-4677-92a8-6d7fda10f175';
  if (hasSource) useCartStore.setState({ items: [{ productId: 'p', shadeId: 's', quantity: 2,
    cartRecommendationSources: [{ ownerId: 'user-1', eventId: 'cart-event' }, { ownerId: 'user-2', eventId: 'other-event' }] }] });
  browser.mockResolvedValue({ type: 'cancel' as WebBrowser.WebBrowserResultType.CANCEL });
  get.mockResolvedValue({ orderId: 'order-1', status: 'pending' });
  await start();
  expect(post).toHaveBeenCalledWith('/api/payments/orders', {
    cartVisitId: mockSearchParams.cartVisitId,
    lines: [{ productId: 'p', shadeId: 's', quantity: hasSource ? 2 : 1,
      ...(hasSource ? { cartRecommendationEventIds: ['cart-event'] } : {}) }],
  }, { expectedUserId: 'user-1' });
});

it('does not treat an unverified success redirect as payment', async () => {
  browser.mockResolvedValue({ type: 'success', url: 'kbeautyar://payment-result?orderId=order-1' });
  get.mockRejectedValue(new Error('offline'));
  const screen = await start();
  expect(useCartStore.getState().items).toHaveLength(1);
  expect(useCartStore.getState().pendingPayment?.orderId).toBe('order-1');
  expect(JSON.stringify(screen.toJSON())).toContain('checkout.checkFailed');
});

it.each(['canceled', 'pending', 'paid'])('uses the server result when a coupon checkout closes: %s', async (status) => {
  mockWallet.data.coupons = [{ id: 'coupon-id', status: 'available' }];
  mockSubtotal = 25000;
  post.mockResolvedValueOnce({ orderId: 'order-1', checkoutUrl: 'https://example.com/pay', localCheckoutPath: '/pay/order-1?token=test', amount: 23000 })
    .mockResolvedValueOnce({ orderId: 'order-1', status });
  browser.mockResolvedValue({ type: 'cancel' as WebBrowser.WebBrowserResultType.CANCEL });
  await act(async () => { mounted = renderer.create(<CheckoutScreen />); });
  const press = async (label: string) => {
    const button = mounted!.root.findAllByType(Button).find(node => node.props.label === label);
    await act(async () => { await button!.props.onPress(); });
  };
  await press('checkout.useCoupon');
  await press('checkout.payment');
  expect(post).toHaveBeenCalledWith('/api/payments/orders', expect.objectContaining({ couponId: 'coupon-id' }), { expectedUserId: 'user-1' });
  expect(browser).toHaveBeenCalledWith('http://localhost:8080/pay/order-1?token=test', 'kbeautyar://payment-result');
  expect(post).toHaveBeenCalledWith('/api/payments/orders/order-1/close', {}, { expectedUserId: 'user-1' });
  expect(useCartStore.getState().pendingPayment?.orderId).toBe(status === 'pending' ? 'order-1' : undefined);
  expect(useCartStore.getState().items).toHaveLength(status === 'paid' ? 0 : 1);
});

it('shows a failure without discarding the cart', async () => {
  browser.mockResolvedValue({ type: 'success', url: 'kbeautyar://payment-result?status=failed' });
  get.mockResolvedValue({ orderId: 'order-1', status: 'pending' });
  const screen = await start();
  expect(useCartStore.getState().items).toHaveLength(1);
  expect(JSON.stringify(screen.toJSON())).toContain('checkout.failed');
});

it('keeps the order pending when the payment window cannot be opened', async () => {
  browser.mockRejectedValue(new Error('browser unavailable'));
  get.mockResolvedValue({ orderId: 'order-1', status: 'pending' });
  const screen = await start();
  expect(useCartStore.getState().pendingPayment?.orderId).toBe('order-1');
  expect(JSON.stringify(screen.toJSON())).toContain('checkout.pending');
});

it('maps start failures to specific notices and can resume from persisted checkoutUrl', async () => {
  post.mockRejectedValueOnce(new ApiError('Payments are not configured', 503, 'payment_unavailable'));
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<CheckoutScreen />); });
  mounted = screen;
  await act(async () => { await screen.root.findByType(Button).props.onPress(); });
  expect(JSON.stringify(screen.toJSON())).toContain('checkout.startFailedUnavailable');

  await act(async () => {
    useCartStore.setState({
      pendingPayment: {
        orderId: 'order-2',
        userId: 'user-1',
        items: [{ productId: 'p', shadeId: 's', quantity: 1 }],
        checkoutUrl: 'https://example.com/pay/order-2',
      },
    });
  });
  browser.mockResolvedValue({ type: 'cancel' as WebBrowser.WebBrowserResultType.CANCEL });
  get.mockResolvedValue({ orderId: 'order-2', status: 'pending' });
  await act(async () => { screen.update(<CheckoutScreen />); });
  const resume = screen.root.findAllByType(Button).find((button) => button.props.label === 'checkout.resume');
  await act(async () => { await resume!.props.onPress(); });
  expect(browser).toHaveBeenCalledWith('https://example.com/pay/order-2', 'kbeautyar://payment-result');
});
