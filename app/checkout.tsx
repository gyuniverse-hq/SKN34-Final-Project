import { useRouter } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { useEffect, useRef, useState } from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Button } from '@/components/ui/Button';
import { Notice } from '@/components/ui/Notice';
import { EmptyState, LoadingState } from '@/components/ui/StateViews';
import { theme } from '@/constants/theme';
import { useCartLines } from '@/hooks/useCartLines';
import { useAuth } from '@/lib/auth';
import { apiGet, apiPost } from '@/lib/api';
import { formatKRW } from '@/lib/format';
import { useI18n } from '@/lib/i18n';
import { loginHref } from '@/lib/routes';
import { useCartStore, type PendingPayment } from '@/store/cartStore';
import type { CreateOrderResponse, OrderStatusResponse } from '@/types';

type PaymentNotice = 'paid' | 'failed' | 'closed' | 'pending' | 'checkFailed' | 'startFailed';

export default function CheckoutScreen() {
  const router = useRouter();
  const { t } = useI18n();
  const { user, ready } = useAuth();
  const { lines, total, query } = useCartLines();
  const pending = useCartStore((s) => s.pendingPayment);
  const setPending = useCartStore((s) => s.setPendingPayment);
  const completePayment = useCartStore((s) => s.completePayment);
  const [notice, setNotice] = useState<PaymentNotice | null>(null);
  const [paymentBusy, setPaymentBusy] = useState(false);
  const busy = useRef(false);
  const [checkoutSession, setCheckoutSession] = useState<{ orderId: string; url: string } | null>(null);

  useEffect(() => {
    if (ready && !user) router.replace(loginHref('checkout'));
  }, [ready, router, user]);

  if (!ready || !user) return <LoadingState />;

  const verifyPayment = async (payment: PendingPayment, unresolved: PaymentNotice = 'pending') => {
    try {
      const result = await apiGet<OrderStatusResponse>(`/api/payments/orders/${encodeURIComponent(payment.orderId)}`);
      if (result.orderId === payment.orderId && result.status === 'paid') {
        completePayment(payment.orderId);
        setCheckoutSession(null);
        setNotice('paid');
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
      await verifyPayment(payment, unresolved);
    } catch {
      await verifyPayment(payment, 'pending');
    }
  };

  const startPayment = async () => {
    if (busy.current || pending) return;
    busy.current = true;
    setPaymentBusy(true);
    setNotice(null);
    try {
      const order = await apiPost<CreateOrderResponse>('/api/payments/orders', {
        lines: lines.map((line) => ({
          productId: line.product.id,
          shadeId: line.shade?.id,
          quantity: line.item.quantity,
        })),
      });
      const payment: PendingPayment = { orderId: order.orderId, userId: user.id, items: lines.map((line) => ({ ...line.item })) };
      setPending(payment);
      setCheckoutSession({ orderId: order.orderId, url: order.checkoutUrl });
      await openPayment(payment, order.checkoutUrl);
    } catch {
      setNotice('startFailed');
    } finally {
      busy.current = false;
      setPaymentBusy(false);
    }
  };

  const checkPending = async () => {
    if (!pending || pending.userId !== user.id || busy.current) return;
    busy.current = true;
    setPaymentBusy(true);
    await verifyPayment(pending);
    busy.current = false;
    setPaymentBusy(false);
  };

  const resumePayment = async () => {
    if (!pending || pending.userId !== user.id || checkoutSession?.orderId !== pending.orderId || busy.current) return;
    busy.current = true;
    setPaymentBusy(true);
    await openPayment(pending, checkoutSession.url);
    busy.current = false;
    setPaymentBusy(false);
  };

  if (notice === 'paid') {
    return <View style={styles.content}><Notice body={t('checkout.paid')} /><Button label={t('checkout.goCart')} onPress={() => router.replace('/cart')} /></View>;
  }
  if (pending) {
    return (
      <View style={styles.content}>
        <Notice tone="warning" body={t(pending.userId !== user.id ? 'checkout.otherUser' : `checkout.${notice && notice !== 'startFailed' ? notice : 'pending'}`)} />
        {pending.userId === user.id ? <Text style={styles.priceNote}>{t('checkout.orderId', { id: pending.orderId })}</Text> : null}
        {pending.userId === user.id ? <Button label={t('checkout.checkStatus')} loading={paymentBusy} onPress={checkPending} /> : null}
        {pending.userId === user.id && checkoutSession?.orderId === pending.orderId ? <Button label={t('checkout.resume')} variant="secondary" disabled={paymentBusy} onPress={resumePayment} /> : null}
      </View>
    );
  }
  if (query.isPending) return <LoadingState />;
  if (lines.length === 0) return <EmptyState icon="cart-outline" title={t('checkout.empty')} />;

  return (
    <SafeAreaView style={styles.screen} edges={['bottom']}>
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.intro}>{t('checkout.intro')}</Text>
        <Text style={styles.heading}>{t('checkout.orderSummary')}</Text>
        <View style={styles.summary}>
          {lines.map((line) => (
            <View key={line.key} style={styles.summaryRow}>
              <Text style={styles.summaryName} numberOfLines={1}>
                {line.product.brand} {line.product.name}
                {line.shade ? ` · ${line.shade.name}` : ''} × {line.item.quantity}
              </Text>
              <Text style={styles.summaryPrice}>{formatKRW(line.lineTotal)}</Text>
            </View>
          ))}
          <View style={[styles.summaryRow, styles.totalRow]}>
            <Text style={styles.totalLabel}>{t('cart.subtotal')}</Text>
            <Text style={styles.totalValue}>{formatKRW(total)}</Text>
          </View>
          <Text style={styles.priceNote}>{t('cart.priceNote')}</Text>
        </View>
        {notice === 'startFailed' ? <Notice tone="warning" body={t('checkout.startFailed')} /> : null}
      </ScrollView>
      <View style={styles.footer}>
        <Button label={t('checkout.payment')} icon="card-outline" loading={paymentBusy} onPress={startPayment} />
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  content: { padding: theme.spacing.lg, paddingBottom: 32 },
  intro: { color: theme.colors.inkMuted, fontSize: theme.font.body, lineHeight: 22, marginBottom: 20 },
  heading: { color: theme.colors.ink, fontSize: theme.font.body, fontWeight: '700', marginBottom: 10 },
  summary: {
    backgroundColor: theme.colors.card,
    borderRadius: theme.radius.md,
    gap: 8,
    padding: 16,
    ...theme.shadow,
  },
  summaryRow: { flexDirection: 'row', gap: 12, justifyContent: 'space-between' },
  summaryName: { color: theme.colors.ink, flex: 1, fontSize: theme.font.small },
  summaryPrice: { color: theme.colors.ink, fontSize: theme.font.small, fontWeight: '600' },
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
