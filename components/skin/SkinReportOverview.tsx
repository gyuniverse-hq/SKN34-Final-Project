import Ionicons from '@expo/vector-icons/Ionicons';
import type { ComponentProps } from 'react';
import { Image, Pressable, StyleSheet, Text, View } from 'react-native';
import { Button } from '@/components/ui/Button';
import { theme } from '@/constants/theme';
import { formatDate } from '@/lib/format';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import type { SkinConcern } from '@/types';
import type { SkinReport, SkinReportMetric, SkinType } from '@/types/skinReport';

const SKIN_TYPE_IMAGES: Record<SkinType, number> = {
  dry: require('@/assets/images/skin-type-dry.png'),
  balanced: require('@/assets/images/skin-type-balanced.png'),
  oily: require('@/assets/images/skin-care-hero.png'),
  combination: require('@/assets/images/skin-care-hero.png'),
  unknown: require('@/assets/images/skin-care-hero.png'),
};

export const REPORT_ICONS: Record<SkinConcern, ComponentProps<typeof Ionicons>['name']> = {
  dryness: 'water-outline', pigmentation: 'sunny-outline', oiliness: 'leaf-outline',
  wrinkles: 'sparkles-outline', pores: 'ellipse-outline', blemish: 'flower-outline', sensitivity: 'shield-checkmark-outline',
};

export function SkinReportOverview({ report, example, expanded, onExpand, onStart }: {
  report: SkinReport; example: boolean;
  expanded: boolean; onExpand: () => void; onStart: () => void;
}) {
  const { t, language } = useI18n();
  return <View style={styles.overview}>
    {example ? <View style={styles.example}>
      <Text style={styles.exampleLabel}>{t('report.sample')}</Text>
      <Text style={styles.copy}>{t('report.sampleBody')}</Text>
      <Button label={t('report.start')} variant="ghost" compact onPress={onStart} />
    </View> : null}
    <Text style={styles.eyebrow}>{t('report.eyebrow')}</Text>
    <Text style={styles.intro}>{t('report.intro')}</Text>
    <Text style={styles.heading} accessibilityRole="header">{t(`report.type.${report.skinType}`)}</Text>
    <Text style={styles.caption}>{t(report.skinTypeSource === 'combined' ? 'report.typeBasisCombined' : report.skinTypeSource === 'analysis' ? 'report.typeBasisModel' : 'report.typeBasis')}</Text>
    <Image source={SKIN_TYPE_IMAGES[report.skinType]} style={styles.hero} resizeMode="contain" accessible={false} />
    <View style={styles.info}>
      <Pressable onPress={onExpand} accessibilityRole="button" accessibilityState={{ expanded }} style={styles.infoHead}>
        <Text style={styles.infoTitle}>{t('report.info')}</Text>
        <Ionicons name={expanded ? 'chevron-up' : 'chevron-down'} size={20} color={theme.colors.inkMuted} />
      </Pressable>
      {expanded ? <View style={styles.infoBody}>
        <View style={styles.review}>
          <Ionicons name="calendar-outline" size={18} color={theme.colors.rose} />
          <Text style={styles.reviewText}>{t('report.review', { date: formatDate(report.reviewAt, language) })}</Text>
        </View>
        <Text style={styles.caption}>{t('report.reviewNote')}</Text>
      </View> : null}
    </View>
  </View>;
}

export function SkinCareHighlights({ metrics, onPress }: { metrics: SkinReportMetric[]; onPress: (concern: SkinConcern) => void }) {
  const { t } = useI18n();
  return <View style={styles.section}>
    <Text style={styles.sectionTitle} accessibilityRole="header">{t('report.priority')}</Text>
    <Text style={styles.copy}>{t('report.priorityBody')}</Text>
    <View style={styles.grid}>
      {metrics.map((metric) => <Pressable key={metric.concern} onPress={() => onPress(metric.concern)}
        accessibilityRole="button" accessibilityLabel={`${t(`concern.${metric.concern}` as TranslationKey)}, ${t(`report.${metric.status}`)}`}
        style={[styles.metric, metric.status === 'care' && styles.metricCare]}>
        <Text style={[styles.status, metric.status === 'care' && styles.statusCare]}>{t(`report.${metric.status}`)}</Text>
        <Text style={styles.metricTitle}>{t(`concern.${metric.concern}` as TranslationKey)}</Text>
        <Text style={styles.caption}>{t(`report.${metric.status}Body`)}</Text>
        <View style={styles.metricFoot}>
          <Text style={styles.source}>{t(`report.${metric.source}`)}</Text>
          <Ionicons name={REPORT_ICONS[metric.concern]} size={32} color={theme.colors.accent} />
        </View>
      </Pressable>)}
    </View>
  </View>;
}

const styles = StyleSheet.create({
  overview: { padding: 24, paddingBottom: 12 },
  eyebrow: { fontSize: 10, letterSpacing: 2.5, fontWeight: '700', color: theme.colors.accent, marginBottom: 24 },
  intro: { fontSize: 17, color: theme.colors.inkMuted, marginBottom: 8 },
  heading: { fontSize: 30, lineHeight: 40, fontWeight: '800', color: theme.colors.ink, letterSpacing: -1 },
  hero: { height: 208, width: '100%', marginVertical: 8 },
  caption: { fontSize: 12, lineHeight: 19, color: theme.colors.inkMuted },
  copy: { fontSize: 14, lineHeight: 22, color: theme.colors.inkMuted },
  info: { backgroundColor: theme.colors.roseSoft, borderRadius: 18, padding: 18 },
  infoHead: { flexDirection: 'row', alignItems: 'center', minHeight: 44, gap: 12 },
  infoTitle: { flex: 1, fontSize: 16, fontWeight: '700', color: theme.colors.ink },
  infoBody: { borderTopWidth: 1, borderTopColor: theme.colors.border, marginTop: 14, paddingTop: 16, gap: 12 },
  review: { flexDirection: 'row', gap: 8, padding: 12, borderRadius: 10, backgroundColor: theme.colors.card, alignItems: 'center' },
  reviewText: { flex: 1, fontSize: 12, fontWeight: '600', color: theme.colors.rose },
  example: { padding: 14, backgroundColor: theme.colors.cream, borderRadius: 12, gap: 5, marginBottom: 24 },
  exampleLabel: { color: theme.colors.rose, fontWeight: '800', fontSize: 12 },
  section: { padding: 24, paddingTop: 28, gap: 8 },
  sectionTitle: { fontSize: 21, fontWeight: '800', color: theme.colors.ink },
  grid: { flexDirection: 'row', gap: 12, marginTop: 10 },
  metric: { flex: 1, minWidth: 0, padding: 16, borderRadius: 16, backgroundColor: theme.colors.chip, gap: 10 },
  metricCare: { backgroundColor: theme.colors.roseSoft, borderWidth: 1, borderColor: theme.colors.border },
  status: { alignSelf: 'flex-start', fontSize: 11, fontWeight: '700', paddingHorizontal: 8, paddingVertical: 5, backgroundColor: theme.colors.card, borderRadius: 6, color: theme.colors.success },
  statusCare: { color: theme.colors.rose, backgroundColor: theme.colors.card },
  metricTitle: { fontSize: 17, fontWeight: '700', color: theme.colors.ink },
  metricFoot: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 6, marginTop: 10 },
  source: { fontSize: 10, color: theme.colors.inkFaint },
});
