import { useLocalSearchParams, useRouter } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { useEffect, useMemo, useRef, useState } from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Button } from '@/components/ui/Button';
import { Notice } from '@/components/ui/Notice';
import { ProductImage } from '@/components/ui/ProductImage';
import { EmptyState, LoadingState } from '@/components/ui/StateViews';
import { theme } from '@/constants/theme';
import { useRewards } from '@/hooks/useRewards';
import { useCartLines } from '@/hooks/useCartLines';
import { useAuth } from '@/lib/auth';
import { API_BASE_URL, ApiError, apiGet, apiPost } from '@/lib/api';
import { arCartEventIds } from '@/lib/arHistory';
import { cartEventIds, waitForCartEvents } from '@/lib/cartAttribution';
import { clearCartArRanks } from '@/lib/cartRecommendations';
import { formatKRW } from '@/lib/format';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import { loginHref, parseCheckoutSelection } from '@/lib/routes';
import { useCartStore, type PendingPayment } from '@/store/cartStore';
import type { CreateOrderResponse, OrderStatusResponse } from '@/types';

type PaymentNotice =
  | 'paid'
  | 'failed'
  | 'closed'
  | 'pending'
  | 'checkFailed'
  | 'startFailed'
  | 'startFailedUnavailable'
  | 'startFailedInvalid'
  | 'startFailedStock'
  | 'startFailedNetwork'
  | 'startFailedAuth'
  | 'canceled';

function startFailedNotice(error: unknown): PaymentNotice {
  if (!(error instanceof ApiError)) return 'startFailed';
  if (error.code === 'payment_unavailable') return 'startFailedUnavailable';
  if (error.code === 'invalid_order') return 'startFailedInvalid';
  if (error.code === 'out_of_stock') return 'startFailedStock';
  if (error.code === 'network' || error.status === 0) return 'startFailedNetwork';
  if (error.status === 401) return 'startFailedAuth';
  return 'startFailed';
}

const PENDING_NOTICE_KEYS = {
  failed: 'checkout.failed',
  closed: 'checkout.closed',
  pending: 'checkout.pending',
  checkFailed: 'checkout.checkFailed',
  otherUser: 'checkout.otherUser',
} as const satisfies Record<string, TranslationKey>;

const START_FAILED_KEYS = {
  startFailed: 'checkout.startFailed',
  startFailedUnavailable: 'checkout.startFailedUnavailable',
  startFailedInvalid: 'checkout.startFailedInvalid',
  startFailedStock: 'checkout.startFailedStock',
  startFailedNetwork: 'checkout.startFailedNetwork',
  startFailedAuth: 'checkout.startFailedAuth',
} as const satisfies Record<string, TranslationKey>;

export default function CheckoutScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{ cartVisitId?: string; productId?: string; shadeId?: string; optionId?: string }>();
  const direct = params.productId !== undefined || params.shadeId !== undefined || params.optionId !== undefined;
  const orderItems = useMemo(() => {
    if (params.optionId !== undefined) return [];
    if (params.productId === undefined && params.shadeId === undefined) return undefined;
    const selection = parseCheckoutSelection({ productId: params.productId, shadeId: params.shadeId });
    return selection ? [{ ...selection, quantity: 1 }] : [];
  }, [params.productId, params.shadeId, params.optionId]);
  const cartVisitId = !direct && typeof params.cartVisitId === 'string' &&
    /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(params.cartVisitId) ? params.cartVisitId : undefined;
  const { t } = useI18n();
  const { user, ready } = useAuth();
  const { lines, total, query } = useCartLines(orderItems);
  const hasSaleOptions = useCartStore(s => !direct && s.items.some(i => !!i.optionId));
  const wallet = useRewards(user?.id);
  const [choice, setChoice] = useState<{ owner: string; id: string } | null>(null);
  const available = wallet.data?.coupons.filter(c => c.status === 'available') ?? [];
  const coupon = total >= 10000 ? available[available.length - 1] : undefined;
  const selected = !!coupon && choice?.owner === user?.id && choice?.id === coupon.id;
  const discount = selected ? Math.min(2000, Math.floor(total / 10)) : 0;
  const dismissPayment = useCartStore(s => s.dismissPayment);
  const pending = useCartStore((s) => s.pendingPayment);
  const setPending = useCartStore((s) => s.setPendingPayment);
  const completePayment = useCartStore((s) => s.completePayment);
  const [notice, setNotice] = useState<PaymentNotice | null>(null);
  const [paymentBusy, setPaymentBusy] = useState(false);
  const busy = useRef(false);

  useEffect(() => {
    if (ready && !user && (!direct || orderItems?.length)) {
      const item = orderItems?.[0];
      const selection = item?.shadeId ? { productId: item.productId, shadeId: item.shadeId } : undefined;
      router.replace(loginHref('checkout', selection));
    }
  }, [direct, orderItems, ready, router, user]);

  if (direct && !orderItems?.length) return <EmptyState icon="cart-outline" title={t('lookPreview.purchaseUnavailable')} />;
  if (!ready || !user) return <LoadingState />;

  const verifyPayment = async (payment: PendingPayment, unresolved: PaymentNotice = 'pending', close = false) => {
    try {
      const path = `/api/payments/orders/${encodeURIComponent(payment.orderId)}`;
      const result = payment.couponId && close
        ? await apiPost<OrderStatusResponse>(path + '/close', {}, { expectedUserId: payment.userId })
        : await apiGet<OrderStatusResponse>(path, { expectedUserId: payment.userId });
      if (result.orderId !== payment.orderId) throw new Error('Unexpected order');
      if (payment.couponId) void wallet.refetch();
      if (result.orderId === payment.orderId && result.status === 'paid') {
        completePayment(payment.orderId);
        if (payment.items.length) clearCartArRanks(payment.userId);
        setNotice('paid');
      } else if (result.status === 'canceled') {
        dismissPayment(payment.orderId);
        setChoice(null);
        setNotice('canceled');
      } else {
        setNotice(unresolved);
      }
    } catch {
      setNotice('checkFailed');
    }
  };

  const openPayment = async (payment: PendingPayment, url: string) => {
    try {
      const result = await WebBrowser.openAuthSessionAsync(url, 'kbeautyar://payment-result');
      const unresolved: PaymentNotice = result.type === 'success' && result.url.includes('status=failed')
        ? 'failed'
        : result.type === 'cancel' || result.type === 'dismiss' ? 'closed' : 'pending';
      await verifyPayment(payment, unresolved, true);
    } catch {
      await verifyPayment(payment, 'pending', true);
    }
  };

  const startPayment = async () => {
    if (busy.current || pending || lines.some(l => !!l.item.optionId) || (!direct && useCartStore.getState().items.some(i => !!i.optionId))) return;
    busy.current = true;
    setPaymentBusy(true);
    setNotice(null);
    try {
      const orderLines = lines.map((line) => {
        const arEvents = arCartEventIds(line.item, user.id);
        const skincareEvents = cartEventIds(line.item, 'skincareCartSources', user.id);
        const cartRecommendationEvents = cartVisitId ? cartEventIds(line.item, 'cartRecommendationSources', user.id) : [];
        return {
          productId: line.product.id,
          shadeId: line.shade?.id,
          quantity: line.item.quantity,
          ...(arEvents.length ? { arCartEventIds: arEvents } : {}),
          ...(skincareEvents.length ? { skincareCartEventIds: skincareEvents } : {}),
          ...(cartRecommendationEvents.length ? { cartRecommendationEventIds: cartRecommendationEvents } : {}),
        };
      });
      const pendingWrites = orderLines.flatMap(line => [
        ...(line.arCartEventIds ?? []), ...(line.skincareCartEventIds ?? []), ...(line.cartRecommendationEventIds ?? []),
      ]);
      if (cartVisitId) pendingWrites.push(cartVisitId);
      await waitForCartEvents(pendingWrites);
      const order = await apiPost<CreateOrderResponse>('/api/payments/orders', {
        lines: orderLines, ...(selected && coupon ? { couponId: coupon.id } : {}), ...(cartVisitId ? { cartVisitId } : {}),
      }, { expectedUserId: user.id });
      const checkoutUrl = __DEV__ && order.localCheckoutPath?.startsWith('/pay/' + order.orderId + '?') && API_BASE_URL
        ? API_BASE_URL + order.localCheckoutPath : order.checkoutUrl;
      const payment: PendingPayment = {
        orderId: order.orderId,
        userId: user.id,
        ...(selected && coupon ? { couponId: coupon.id } : {}),
        // This snapshot is used to remove paid cart items. A direct order owns no cart items.
        items: direct ? [] : lines.map((line) => ({ ...line.item })),
        checkoutUrl,
      };
      setPending(payment);
      await openPayment(payment, checkoutUrl);
    } catch (error) {
      if (selected) void wallet.refetch();
      setNotice(startFailedNotice(error));
    } finally {
      busy.current = false;
      setPaymentBusy(false);
    }
  };

  const checkPending = async () => {
    if (!pending || pending.userId !== user.id || busy.current) return;
    busy.current = true;
    setPaymentBusy(true);
    await verifyPayment(pending, 'pending', !!pending.couponId);
    busy.current = false;
    setPaymentBusy(false);
  };

  const resumePayment = async () => {
    if (!pending || pending.userId !== user.id || !pending.checkoutUrl || busy.current) return;
    busy.current = true;
    setPaymentBusy(true);
    await openPayment(pending, pending.checkoutUrl);
    busy.current = false;
    setPaymentBusy(false);
  };

  if (notice === 'paid') {
    return (
      <View style={styles.content}>
        <Notice body={t('checkout.paid')} />
        <Button label={t('checkout.goShop')} onPress={() => router.replace('/shop')} />
        <Button label={t('checkout.goHome')} variant="secondary" onPress={() => router.replace('/')} />
        <Button label={t('checkout.goCart')} variant="ghost" onPress={() => router.replace('/cart')} />
      </View>
    );
  }
  if (pending) {
    const pendingKey = pending.userId !== user.id
      ? PENDING_NOTICE_KEYS.otherUser
      : PENDING_NOTICE_KEYS[
          notice === 'failed' || notice === 'closed' || notice === 'checkFailed' || notice === 'pending'
            ? notice
            : 'pending'
        ];
    return (
      <View style={styles.content}>
        <Text style={styles.pendingTitle}>{t('checkout.pendingTitle')}</Text>
        <Notice tone="warning" body={t(pendingKey)} />
        {pending.userId === user.id ? <Text style={styles.priceNote}>{t('checkout.orderId', { id: pending.orderId })}</Text> : null}
        {pending.userId === user.id ? <Button label={t(pending.couponId ? 'checkout.closeOrder' : 'checkout.checkStatus')} loading={paymentBusy} onPress={checkPending} /> : null}
        {pending.userId === user.id && !pending.couponId && pending.checkoutUrl ? (
          <Button label={t('checkout.resume')} variant="secondary" disabled={paymentBusy} onPress={resumePayment} />
        ) : null}
        {pending.userId === user.id && !pending.couponId ? (
          <Button
            label={t('checkout.dismissPending')}
            variant="ghost"
            disabled={paymentBusy}
            onPress={() => { dismissPayment(pending.orderId); setNotice(null); }}
          />
        ) : null}
      </View>
    );
  }
  if (hasSaleOptions) return <View style={styles.content}><Notice body={t('sale.checkoutBlocked')} /><Button label={t('checkout.goCart')} onPress={() => router.replace('/cart')} /></View>;
  if (query.isPending) return <LoadingState />;
  if (lines.length === 0) return <EmptyState icon="cart-outline" title={t(direct ? 'lookPreview.purchaseUnavailable' : 'checkout.empty')} />;

  return (
    <SafeAreaView style={styles.screen} edges={['bottom']}>
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.intro}>{t('checkout.intro')}</Text>
        <Text style={styles.heading}>{t('checkout.orderSummary')}</Text>
        <View style={styles.summary}>
          {lines.map((line) => (
            <View key={line.key} style={styles.summaryRow}>
              <ProductImage uri={line.product.imageUrl} category={line.product.category} style={styles.thumb} compact />
              <View style={styles.summaryCopy}>
                <Text style={styles.summaryBrand} numberOfLines={1}>{line.product.brand}</Text>
                <Text style={styles.summaryName} numberOfLines={2}>
                  {line.product.name}
                  {line.shade ? ` · ${line.shade.name}` : ''}
                </Text>
                <Text style={styles.summaryQty}>× {line.item.quantity}</Text>
              </View>
              <Text style={styles.summaryPrice}>{formatKRW(line.lineTotal)}</Text>
            </View>
          ))}
          <View style={[styles.totalRowInner, styles.totalRow]}>
            <Text style={styles.totalLabel}>{t('cart.subtotal')}</Text>
            <Text style={styles.totalValue}>{formatKRW(total)}</Text>
          </View>
          {available.length > 0 && <Button variant="secondary" disabled={!coupon} label={t(selected ? 'checkout.removeCoupon' : 'checkout.useCoupon')}
            onPress={() => setChoice(!selected && coupon ? { owner: user.id, id: coupon.id } : null)} />}
          {available.length > 0 && !coupon && <Text style={styles.priceNote}>{t('rewards.conditions')}</Text>}
          {discount > 0 && <>
            <View style={styles.summaryRow}><Text style={styles.summaryName}>{t('checkout.discount')}</Text><Text>−{formatKRW(discount)}</Text></View>
            <View style={styles.summaryRow}><Text style={styles.totalLabel}>{t('checkout.payable')}</Text><Text style={styles.totalValue}>{formatKRW(total - discount)}</Text></View>
          </>}
          <Text style={styles.priceNote}>{t('cart.priceNote')}</Text>
        </View>
        {notice === 'canceled' && <Notice body={t('checkout.canceled')} />}
        {notice && notice in START_FAILED_KEYS ? (
          <Notice tone="warning" body={t(START_FAILED_KEYS[notice as keyof typeof START_FAILED_KEYS])} />
        ) : null}
      </ScrollView>
      <View style={styles.footer}>
        <Button label={t('checkout.payment')} icon="card-outline" loading={paymentBusy} onPress={startPayment} />
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  content: { padding: theme.spacing.lg, paddingBottom: 32, gap: 12 },
  intro: { color: theme.colors.inkMuted, fontSize: theme.font.body, lineHeight: 22, marginBottom: 8 },
  heading: { color: theme.colors.ink, fontSize: theme.font.body, fontWeight: '700', marginBottom: 2 },
  pendingTitle: { color: theme.colors.ink, fontSize: theme.font.title, fontWeight: '800', marginBottom: 4 },
  summary: {
    backgroundColor: theme.colors.card,
    borderRadius: theme.radius.md,
    gap: 14,
    padding: 16,
    ...theme.shadow,
  },
  summaryRow: { flexDirection: 'row', gap: 12, alignItems: 'flex-start' },
  thumb: { width: 56, height: 56, borderRadius: theme.radius.sm },
  summaryCopy: { flex: 1, gap: 2 },
  summaryBrand: { color: theme.colors.inkFaint, fontSize: theme.font.caption, fontWeight: '600' },
  summaryName: { color: theme.colors.ink, fontSize: theme.font.small, lineHeight: 18 },
  summaryQty: { color: theme.colors.inkMuted, fontSize: theme.font.caption },
  summaryPrice: { color: theme.colors.ink, fontSize: theme.font.small, fontWeight: '600' },
  totalRowInner: { flexDirection: 'row', gap: 12, justifyContent: 'space-between' },
  totalRow: { borderTopColor: theme.colors.border, borderTopWidth: StyleSheet.hairlineWidth, marginTop: 4, paddingTop: 10 },
  totalLabel: { color: theme.colors.inkMuted, fontSize: theme.font.body },
  totalValue: { color: theme.colors.ink, fontSize: theme.font.title, fontWeight: '800' },
  priceNote: { color: theme.colors.inkFaint, fontSize: 11 },
  footer: {
    borderTopColor: theme.colors.border,
    borderTopWidth: StyleSheet.hairlineWidth,
    paddingBottom: 8,
    paddingHorizontal: theme.spacing.lg,
    paddingTop: 12,
  },
});
