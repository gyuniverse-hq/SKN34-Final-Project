import React from 'react';
import renderer, { act } from 'react-test-renderer';
import * as WebBrowser from 'expo-web-browser';
import CheckoutScreen from '@/app/checkout';
import { Button } from '@/components/ui/Button';
import { apiGet, apiPost } from '@/lib/api';
import { useCartStore } from '@/store/cartStore';

jest.mock('@expo/vector-icons/Ionicons', () => 'Ionicons');
jest.mock('@/components/ui/StateViews', () => ({ EmptyState: 'EmptyState', LoadingState: 'LoadingState' }));
jest.mock('expo-router', () => ({ useRouter: () => ({ replace: jest.fn() }) }));
jest.mock('expo-web-browser', () => ({ openAuthSessionAsync: jest.fn() }));
jest.mock('@/lib/auth', () => ({ useAuth: () => ({ user: { id: 'user-1' }, ready: true }) }));
jest.mock('@/lib/api', () => ({ apiGet: jest.fn(), apiPost: jest.fn() }));
jest.mock('@/lib/i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }));
jest.mock('@/hooks/useCartLines', () => {
  const { useCartStore } = jest.requireActual('@/store/cartStore');
  return {
    useCartLines: () => ({
      lines: [{ key: 'p::s', item: useCartStore.getState().items[0] ?? { productId: 'p', shadeId: 's', quantity: 1 },
        product: { id: 'p', brand: 'B', name: 'P' }, shade: { id: 's', name: 'S' }, lineTotal: 1000 }],
      total: 1000,
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
  expect(get).toHaveBeenCalledWith('/api/payments/orders/order-1');
  expect(useCartStore.getState().items).toHaveLength(0);
  expect(JSON.stringify(screen.toJSON())).toContain('checkout.paid');
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
  expect(useCartStore.getState().pendingPayment?.orderId).toBe('order-1');
  expect(JSON.stringify(screen.toJSON())).toContain('checkout.closed');
  get.mockResolvedValue({ orderId: 'order-1', status: 'paid' });
  const check = screen.root.findAllByType(Button).find((button) => button.props.label === 'checkout.checkStatus');
  await act(async () => { await check!.props.onPress(); });
  expect(useCartStore.getState().items).toHaveLength(0);
  expect(JSON.stringify(screen.toJSON())).toContain('checkout.paid');
});

it('does not treat an unverified success redirect as payment', async () => {
  browser.mockResolvedValue({ type: 'success', url: 'kbeautyar://payment-result?orderId=order-1' });
  get.mockRejectedValue(new Error('offline'));
  const screen = await start();
  expect(useCartStore.getState().items).toHaveLength(1);
  expect(useCartStore.getState().pendingPayment?.orderId).toBe('order-1');
  expect(JSON.stringify(screen.toJSON())).toContain('checkout.checkFailed');
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
