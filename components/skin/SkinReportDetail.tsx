import Ionicons from '@expo/vector-icons/Ionicons';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { theme } from '@/constants/theme';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import type { SkinConcern } from '@/types';
import type { SkinReportMetric } from '@/types/skinReport';
import type { SkinPreview } from '@/types/skin';
import { SkinPreviewPhoto } from './SkinPreviewPhoto';
import { REPORT_ICONS } from './SkinReportOverview';

export function SkinConcernRail({ concerns, active, onChange, skinType = false }: { concerns: readonly SkinConcern[]; active: SkinConcern; onChange: (c: SkinConcern) => void; skinType?: boolean }) {
  const { t } = useI18n();
  return <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.rail}>
    {concerns.map((c) => <Pressable key={c} accessibilityRole="tab" accessibilityState={{ selected: c === active }}
      onPress={() => onChange(c)} style={[styles.chip, c === active && styles.chipOn]}>
      <Text style={[styles.chipText, c === active && styles.chipTextOn]}>{t(skinType && c === 'dryness' ? 'report.skinType' : `concern.${c}` as TranslationKey)}</Text>
    </Pressable>)}
  </ScrollView>;
}

export function SkinReportDetail({ metrics, active, onChange, preview }: { metrics: SkinReportMetric[]; active: SkinConcern; onChange: (c: SkinConcern) => void; preview: SkinPreview | null }) {
  const { t } = useI18n();
  const imageMetrics = metrics.filter((m) => m.source === 'analysis' || m.source === 'combined');
  // The solution tab may still have a survey-only concern selected.
  const metric = imageMetrics.find((m) => m.concern === active) ?? imageMetrics[0];
  if (!metric) return null;
  const concern = metric.concern;
  return <View style={styles.content}>
    <Text style={styles.title} accessibilityRole="header">{t('report.details')}</Text>
    <Text style={styles.body}>{t('report.detailBody')}</Text>
    <SkinConcernRail concerns={imageMetrics.map((m) => m.concern)} active={concern} onChange={onChange} skinType />
    {preview ? <>
      <SkinPreviewPhoto preview={preview} active={concern} />
      <Text style={styles.caption}>{t(concern === 'blemish' ? 'report.previewWhole' : 'report.previewNotice')}</Text>
    </> : <View style={styles.privacy}>
      <Ionicons name="shield-checkmark-outline" size={28} color={theme.colors.rose} />
      <View style={styles.flex}><Text style={styles.cardTitle}>{t('report.noPhoto')}</Text><Text style={styles.caption}>{t('report.noPhotoBody')}</Text></View>
    </View>}
    <View style={styles.result}>
      <View style={styles.row}><Ionicons name={REPORT_ICONS[concern]} size={28} color={theme.colors.accent} /><Text style={styles.cardTitle}>{t(metric.skinType ? 'report.skinType' : `concern.${concern}` as TranslationKey)}</Text></View>
      <Text style={styles.source}>{t(`report.${metric.source}`)}</Text>
      <Text style={styles.value}>{metric.skinType ? t(`report.type.${metric.skinType}`) : metric.value === null ? t('report.unknown')
        : concern === 'blemish' ? t(metric.value === 1 ? 'skin.acneDetected' : 'skin.acneNotDetected') : t('skin.grade', { grade: metric.value })}</Text>
      {!metric.skinType ? <Text style={[styles.status, metric.status === 'care' && styles.care, metric.status === 'fair' && styles.fair]}>{t(`report.${metric.status}`)}</Text> : null}
      <Text style={styles.body}>{t(metric.skinType ? metric.source === 'combined' ? 'report.typeBasisCombined' : 'report.typeBasisModel' : 'report.modelNote')}</Text>
    </View>
  </View>;
}

const styles = StyleSheet.create({
  content: { padding: 24, gap: 16 }, title: { fontSize: 21, color: theme.colors.ink, fontWeight: '800' },
  body: { color: theme.colors.inkMuted, fontSize: 14, lineHeight: 23 }, caption: { color: theme.colors.inkMuted, fontSize: 12, lineHeight: 20 },
  privacy: { flexDirection: 'row', alignItems: 'center', padding: 16, gap: 14, backgroundColor: theme.colors.roseSoft, borderRadius: 14 },
  flex: { flex: 1, gap: 6 }, cardTitle: { fontSize: 15, fontWeight: '700', color: theme.colors.ink },
  rail: { gap: 8, paddingVertical: 3 }, chip: { minHeight: 44, justifyContent: 'center', paddingHorizontal: 18, borderWidth: 1, borderColor: theme.colors.border, borderRadius: 24, backgroundColor: theme.colors.card },
  chipOn: { backgroundColor: theme.colors.rose, borderColor: theme.colors.rose }, chipText: { fontSize: 13, color: theme.colors.inkMuted }, chipTextOn: { color: theme.colors.white, fontWeight: '700' },
  result: { gap: 16, padding: 24, borderRadius: 18, backgroundColor: theme.colors.card, borderWidth: 1, borderColor: theme.colors.border },
  row: { flexDirection: 'row', alignItems: 'center', gap: 10 }, source: { fontSize: 11, color: theme.colors.accent, fontWeight: '700' },
  value: { fontSize: 30, color: theme.colors.ink, fontWeight: '800' }, status: { alignSelf: 'flex-start', color: theme.colors.success, backgroundColor: theme.colors.chip, paddingVertical: 6, paddingHorizontal: 10, borderRadius: 8, fontSize: 12, fontWeight: '700' },
  care: { color: theme.colors.rose, backgroundColor: theme.colors.roseSoft },
  fair: { color: theme.colors.warning, backgroundColor: theme.colors.warningBg },
});
