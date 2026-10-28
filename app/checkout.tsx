import { useRouter } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { useEffect, useState } from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Button } from '@/components/ui/Button';
import { Notice } from '@/components/ui/Notice';
import { EmptyState, LoadingState } from '@/components/ui/StateViews';
import { theme } from '@/constants/theme';
import { useCartLines } from '@/hooks/useCartLines';
import { useAuth } from '@/lib/auth';
import { apiPost } from '@/lib/api';
import { formatKRW } from '@/lib/format';
import { useI18n } from '@/lib/i18n';
import { loginHref } from '@/lib/routes';
import type { CreateOrderResponse } from '@/types';

export default function CheckoutScreen() {
  const router = useRouter();
  const { t } = useI18n();
  const { user, ready } = useAuth();
  const { lines, total, query } = useCartLines();
  const [showPaymentNotice, setShowPaymentNotice] = useState(false);
  const [paymentBusy, setPaymentBusy] = useState(false);

  useEffect(() => {
    if (ready && !user) router.replace(loginHref('checkout'));
  }, [ready, router, user]);

  if (!ready || !user || query.isPending) return <LoadingState />;
  if (lines.length === 0) return <EmptyState icon="cart-outline" title={t('checkout.empty')} />;

  const startPayment = async () => {
    setPaymentBusy(true);
    setShowPaymentNotice(false);
    try {
      const order = await apiPost<CreateOrderResponse>('/api/payments/orders', {
        lines: lines.map((line) => ({
          productId: line.product.id,
          shadeId: line.shade?.id,
          quantity: line.item.quantity,
        })),
      });
      await WebBrowser.openAuthSessionAsync(order.checkoutUrl, 'kbeautyar://payment-result');
    } catch {
      setShowPaymentNotice(true);
    } finally {
      setPaymentBusy(false);
    }
  };

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
        {showPaymentNotice ? <Notice tone="warning" body={t('checkout.paymentNotice')} /> : null}
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
