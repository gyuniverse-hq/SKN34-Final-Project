import Ionicons from '@expo/vector-icons/Ionicons';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { EmptyState } from '@/components/ui/StateViews';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';

const COUPON_GOAL = 7;

export default function RewardsScreen() {
  const { t } = useI18n();
  const count = 0;

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      <View style={styles.card}>
        <Text style={styles.progressText}>{t('rewards.progress', { count, goal: COUPON_GOAL })}</Text>
        <View style={styles.stamps}>
          {Array.from({ length: COUPON_GOAL }, (_, i) => (
            <View key={i} style={[styles.stamp, i < count && styles.stampFilled]}>
              <Ionicons name="sparkles" size={16} color={i < count ? theme.colors.white : theme.colors.inkFaint} />
            </View>
          ))}
        </View>
        <View style={styles.rule}>
          <Ionicons name="calendar-outline" size={16} color={theme.colors.inkMuted} />
          <Text style={styles.ruleText}>{t('rewards.rule')}</Text>
        </View>
        <View style={styles.rule}>
          <Ionicons name="star-outline" size={16} color={theme.colors.inkMuted} />
          <Text style={styles.ruleText}>{t('rewards.memberRule')}</Text>
        </View>
      </View>

      <Text style={styles.sectionTitle}>{t('rewards.coupons')}</Text>
      <View style={styles.empty}>
        <EmptyState icon="ticket-outline" title={t('rewards.couponsEmpty')} />
      </View>
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
  ruleText: { flex: 1, fontSize: theme.font.small, color: theme.colors.inkMuted },
  sectionTitle: { fontSize: theme.font.title, fontWeight: '800', color: theme.colors.ink, marginTop: 26, marginBottom: 8 },
  empty: { borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.colors.border, borderStyle: 'dashed' },
});
