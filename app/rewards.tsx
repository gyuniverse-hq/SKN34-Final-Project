import Ionicons from '@expo/vector-icons/Ionicons';
import { useRouter } from 'expo-router';
import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { EmptyState, LoadingState } from '@/components/ui/StateViews';
import { useRewards } from '@/hooks/useRewards';
import { useAuth } from '@/lib/auth';
import { apiPost } from '@/lib/api';
import { notify } from '@/lib/confirm';
import type { OrderStatusResponse } from '@/types';
import { loginHref } from '@/lib/routes';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';

export default function RewardsScreen() {
  const { user, ready } = useAuth();
  const router = useRouter();
  const { t } = useI18n();
  if (!ready) return <LoadingState />;
  if (!user) return <View style={styles.content}><EmptyState icon="ticket-outline" title={t('rewards.login')} />
    <Button label={t('my.login')} onPress={() => router.push(loginHref('rewards'))} /></View>;
  return <MemberRewards key={user.id} owner={user.id} />;
}

function MemberRewards({ owner }: { owner: string }) {
  const { t, language } = useI18n();
  const wallet = useRewards(owner);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const attend = async () => {
    if (busy || wallet.data?.checkedToday) return;
    setFailed(false);
    setBusy(true);
    try { await wallet.attend(); }
    catch { setFailed(true); }
    finally { setBusy(false); }
  };
  const closeOrder = async (id: string) => {
    if (busy) return;
    setBusy(true);
    try {
      const order = await apiPost<OrderStatusResponse>(`/api/payments/orders/${encodeURIComponent(id)}/close`, {}, { expectedUserId: owner });
      if (order.status === 'pending') notify(t('checkout.pending'));
      await wallet.refetch();
    } catch { notify(t('checkout.checkFailed')); }
    finally { setBusy(false); }
  };
  if (!wallet.data && wallet.isPending) return <LoadingState />;
  if (!wallet.data) return <View style={styles.content}><Text>{t('rewards.error')}</Text>
    <Button label={t('common.retry')} onPress={() => void wallet.refetch()} /></View>;
  const { stamps: count, goal, coupons, checkedToday } = wallet.data;

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      <View style={styles.card}>
        <Text style={styles.progressText}>{t('rewards.progress', { count, goal })}</Text>
        <View style={styles.stamps}>
          {Array.from({ length: goal }, (_, i) => (
            <View key={i} style={[styles.stamp, i < count && styles.stampFilled]}>
              <Ionicons name="sparkles" size={16} color={i < count ? theme.colors.white : theme.colors.inkFaint} />
            </View>
          ))}
        </View>
        <View style={styles.rule}>
          <Ionicons name="calendar-outline" size={16} color={theme.colors.inkMuted} />
          <Text style={[styles.ruleText, styles.ruleCopy]}>{t('rewards.rule')}</Text>
        </View>
        <View style={styles.rule}>
          <Ionicons name="star-outline" size={16} color={theme.colors.inkMuted} />
          <Text style={[styles.ruleText, styles.ruleCopy]}>{t('rewards.memberRule')}</Text>
        </View>
        {failed && <Text accessibilityRole="alert" style={styles.ruleText}>{t('rewards.checkFailed')}</Text>}
        <Button label={t(checkedToday ? 'rewards.attended' : 'rewards.attend')} loading={busy}
          disabled={checkedToday || busy} onPress={attend} />
      </View>

      <Text style={styles.sectionTitle}>{t('rewards.coupons')}</Text>
      {coupons.length ? coupons.map(coupon => <View key={coupon.id} style={styles.coupon}>
        <Text style={styles.couponTitle}>{t('rewards.coupon')}</Text>
        <Text style={styles.ruleText}>{t('rewards.conditions')}</Text>
        <Text style={styles.ruleText}>{t('rewards.validThrough', { date: new Date(Date.parse(coupon.expiresAt) - 1)
          .toLocaleDateString(language, { timeZone: 'Asia/Seoul' }) })} · {t(`rewards.${coupon.status}`)}</Text>
        {coupon.reservedOrderId && <Button label={t('checkout.closeOrder')} variant="secondary" disabled={busy}
          onPress={() => void closeOrder(coupon.reservedOrderId!)} />}
      </View>) : <View style={styles.empty}><EmptyState icon="ticket-outline" title={t('rewards.couponsEmpty')} /></View>}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  content: { padding: theme.spacing.lg, paddingBottom: 40 },
  card: { backgroundColor: theme.colors.card, borderRadius: theme.radius.lg, padding: 18, gap: 12, ...theme.shadow },
  progressText: { fontSize: theme.font.title, fontWeight: '800', color: theme.colors.ink },
  stamps: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginVertical: 4 },
  stamp: {
    width: 38,
    height: 38,
    borderRadius: 19,
    borderWidth: 1.5,
    borderColor: theme.colors.border,
    borderStyle: 'dashed',
    alignItems: 'center',
    justifyContent: 'center',
  },
  stampFilled: { backgroundColor: theme.colors.rose, borderColor: theme.colors.rose, borderStyle: 'solid' },
  rule: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  ruleCopy: { flex: 1 },
  ruleText: { fontSize: theme.font.small, color: theme.colors.inkMuted },
  sectionTitle: { fontSize: theme.font.title, fontWeight: '800', color: theme.colors.ink, marginTop: 26, marginBottom: 8 },
  coupon: { backgroundColor: theme.colors.card, borderRadius: theme.radius.md, padding: 16, gap: 5, marginBottom: 8 },
  couponTitle: { color: theme.colors.roseDark, fontSize: theme.font.body, fontWeight: '700' },
  empty: { borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.colors.border, borderStyle: 'dashed' },
});
