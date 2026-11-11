import Ionicons from '@expo/vector-icons/Ionicons';
import { LinearGradient } from 'expo-linear-gradient';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { theme } from '@/constants/theme';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import { displayCareGoal } from '@/lib/skincare';
import type { SkinConcern } from '@/types';
import type { SkinReportMetric } from '@/types/skinReport';
import type { SkinPreview } from '@/types/skin';
import { SkinPreviewPhoto } from './SkinPreviewPhoto';
import { REPORT_ICONS } from './SkinReportOverview';

export function SkinConcernRail({ concerns, active, onChange, skinType = false, goalLabels = false }: { concerns: readonly SkinConcern[]; active: SkinConcern; onChange: (c: SkinConcern) => void; skinType?: boolean; goalLabels?: boolean }) {
  const { t } = useI18n();
  return <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.rail}>
    {concerns.map((c) => <Pressable key={c} accessibilityRole="tab" accessibilityState={{ selected: c === active }}
      onPress={() => onChange(c)} style={[styles.chip, c === active && styles.chipOn]}>
      <Text style={[styles.chipText, c === active && styles.chipTextOn]}>{t(goalLabels ? `support.priorityChoice.${displayCareGoal(c)}` : skinType && c === 'dryness' ? 'report.skinType' : `concern.${c}` as TranslationKey)}</Text>
    </Pressable>)}
  </ScrollView>;
}

export function SkinReportDetail({ metrics, active, onChange, preview }: { metrics: SkinReportMetric[]; active: SkinConcern; onChange: (c: SkinConcern) => void; preview: SkinPreview | null }) {
  const { t } = useI18n();
  const imageMetrics = metrics.filter((m) => (m.source === 'analysis' || m.source === 'combined') &&
    ((m.skinType !== undefined && m.skinType !== 'unknown') || m.regions.length > 0 ||
      (m.concern === 'blemish' && m.value !== null)));
  // The solution tab may still have a survey-only concern selected.
  const metric = imageMetrics.find((m) => m.concern === active) ?? imageMetrics[0];
  const concern = metric?.concern ?? 'dryness';
  const score = metric?.modelScore;
  return <View style={styles.content}>
    <Text style={styles.title} accessibilityRole="header">{t('report.details')}</Text>
    {preview ? <>
      <SkinPreviewPhoto preview={preview} active={concern} />
      <Text style={styles.caption}>{t(concern === 'blemish' ? 'report.previewWhole' : 'report.previewNotice')}</Text>
    </> : <View style={styles.privacy}>
      <Ionicons name="shield-checkmark-outline" size={28} color={theme.colors.rose} />
      <View style={styles.flex}><Text style={styles.cardTitle}>{t('report.noPhoto')}</Text><Text style={styles.caption}>{t('report.noPhotoBody')}</Text></View>
    </View>}
    {metric && <SkinConcernRail concerns={imageMetrics.map((m) => m.concern)} active={concern} onChange={onChange} skinType />}
    {metric && <View style={styles.result}>
      <View style={styles.row}>
        <Ionicons name={REPORT_ICONS[concern]} size={24} color={theme.colors.accent} />
        <Text style={[styles.cardTitle, styles.resultTitle]}>{t(metric.skinType ? 'report.skinType' : `concern.${concern}` as TranslationKey)}</Text>
        <Text style={[styles.status, !metric.skinType && metric.status === 'care' && styles.statusCare]}>
          {metric.skinType ? t(`report.type.${metric.skinType}`) : concern === 'blemish' && metric.value !== null ? t(metric.value === 1 ? 'skin.acneDetected' : 'skin.acneNotDetected') : t(`report.${metric.status}`)}
        </Text>
      </View>
      <Text style={[styles.caption, styles.resultDescription]}>{t(metric.skinType ? 'report.skinTypeDescription' : `report.${metric.status}Body`)}</Text>
      <View style={styles.scoreSlot}>
        {score !== undefined && <>
          <LinearGradient colors={['#A8D8B4', '#F5E7BE', '#EFA6AD']}
            start={{ x: 0, y: 0.5 }} end={{ x: 1, y: 0.5 }} style={styles.scoreTrack} />
          <View style={[styles.scoreDot, { left: `${score * 100}%` }]} />
        </>}
      </View>
    </View>}
  </View>;
}

const styles = StyleSheet.create({
  content: { padding: 24, gap: 16 }, title: { fontSize: 21, color: theme.colors.ink, fontWeight: '800' },
  caption: { color: theme.colors.inkMuted, fontSize: 12, lineHeight: 20 },
  privacy: { flexDirection: 'row', alignItems: 'center', padding: 16, gap: 14, backgroundColor: theme.colors.roseSoft, borderRadius: 14 },
  flex: { flex: 1, gap: 6 }, cardTitle: { fontSize: 15, fontWeight: '700', color: theme.colors.ink },
  rail: { gap: 8, paddingVertical: 3 }, chip: { minHeight: 44, justifyContent: 'center', paddingHorizontal: 18, borderWidth: 1, borderColor: theme.colors.border, borderRadius: 24, backgroundColor: theme.colors.card },
  chipOn: { backgroundColor: theme.colors.rose, borderColor: theme.colors.rose }, chipText: { fontSize: 13, color: theme.colors.inkMuted }, chipTextOn: { color: theme.colors.white, fontWeight: '700' },
  result: { gap: 10, padding: 18, borderRadius: 18, backgroundColor: theme.colors.card, borderWidth: 1, borderColor: theme.colors.border },
  row: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  resultTitle: { flex: 1 },
  status: { fontSize: 13, color: theme.colors.success, fontWeight: '700', flexShrink: 1, textAlign: 'right' },
  statusCare: { color: theme.colors.rose },
  resultDescription: { minHeight: 40 },
  scoreSlot: { height: 14, marginHorizontal: 6, justifyContent: 'center' },
  scoreTrack: { height: 8, borderRadius: 4 },
  scoreDot: { position: 'absolute', top: 1, width: 12, height: 12, borderRadius: 6,
    transform: [{ translateX: -6 }], backgroundColor: theme.colors.ink, borderWidth: 2, borderColor: theme.colors.card },
});
