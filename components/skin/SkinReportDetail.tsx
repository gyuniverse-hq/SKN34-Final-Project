import Ionicons from '@expo/vector-icons/Ionicons';
import { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Switch, Text, View } from 'react-native';
import { theme } from '@/constants/theme';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import type { SkinConcern } from '@/types';
import type { SkinReportMetric } from '@/types/skinReport';
import type { SkinPreview } from '@/types/skin';
import { SkinPreviewPhoto } from './SkinPreviewPhoto';
import { REPORT_ICONS } from './SkinReportOverview';

export function SkinConcernRail({ concerns, active, onChange }: { concerns: readonly SkinConcern[]; active: SkinConcern; onChange: (c: SkinConcern) => void }) {
  const { t } = useI18n();
  return <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.rail}>
    {concerns.map((c) => <Pressable key={c} accessibilityRole="tab" accessibilityState={{ selected: c === active }}
      onPress={() => onChange(c)} style={[styles.chip, c === active && styles.chipOn]}>
      <Text style={[styles.chipText, c === active && styles.chipTextOn]}>{t(`concern.${c}` as TranslationKey)}</Text>
    </Pressable>)}
  </ScrollView>;
}

export function SkinReportDetail({ metrics, active, onChange, preview }: { metrics: SkinReportMetric[]; active: SkinConcern; onChange: (c: SkinConcern) => void; preview: SkinPreview | null }) {
  const { t } = useI18n();
  const [regionsVisible, setRegionsVisible] = useState(true);
  const metric = metrics.find((m) => m.concern === active)!;
  const question = active === 'dryness' ? 'tightness' : active === 'oiliness' ? 'oiliness' : 'sensitivity';
  const answer = metric.value === null ? t('skin.unknown')
    : t(`skin.answer.${active === 'oiliness' ? 'oil' : 'frequency'}.${metric.value}` as TranslationKey);
  return <View style={styles.content}>
    <Text style={styles.title} accessibilityRole="header">{t('report.details')}</Text>
    <Text style={styles.body}>{t('report.detailBody')}</Text>
    <SkinConcernRail concerns={metrics.map((m) => m.concern)} active={active} onChange={onChange} />
    {preview ? <>
      <SkinPreviewPhoto preview={preview} active={active} />
      <Text style={styles.caption}>{t(metric.source === 'unavailable' ? 'report.unavailableNote' : active === 'blemish' ? 'report.previewWhole' : metric.source === 'survey' ? 'report.previewSurvey' : 'report.previewNotice')}</Text>
    </> : <View style={styles.privacy}>
      <Ionicons name="shield-checkmark-outline" size={28} color={theme.colors.rose} />
      <View style={styles.flex}><Text style={styles.cardTitle}>{t('report.noPhoto')}</Text><Text style={styles.caption}>{t('report.noPhotoBody')}</Text></View>
    </View>}
    <View style={styles.result}>
      <View style={styles.row}><Ionicons name={REPORT_ICONS[active]} size={28} color={theme.colors.accent} /><Text style={styles.cardTitle}>{t(`concern.${active}` as TranslationKey)}</Text></View>
      <Text style={styles.source}>{t(`report.${metric.source}`)}</Text>
      <Text style={styles.value}>{metric.source === 'unavailable' ? t('report.notAnalyzed') : metric.value === null ? t('report.unknown') : metric.source === 'survey' ? answer
        : active === 'blemish' ? t(metric.value === 1 ? 'skin.acneDetected' : 'skin.acneNotDetected') : t('skin.grade', { grade: metric.value })}</Text>
      <Text style={[styles.status, metric.status === 'care' && styles.care]}>{t(`report.${metric.status}`)}</Text>
      <Text style={styles.body}>{t(metric.source === 'unavailable' ? 'report.unavailableNote' : metric.source === 'survey' ? 'report.surveyNote' : 'report.modelNote')}</Text>
      {metric.source === 'survey' ? <Text style={styles.question}>{t(`skin.question.${question}`)}</Text> : null}
      {metric.value !== null && metric.maximum !== null && active !== 'blemish' ? <Text style={styles.caption}>{t('report.maxGrade', { grade: metric.value, max: metric.maximum })}</Text> : null}
    </View>
    {metric.source === 'analysis' && metric.regions.length > 0 ? <>
      <View style={styles.switchRow}><Text style={styles.cardTitle}>{t('report.regions')}</Text>
        <Switch accessibilityLabel={t('report.regions')} value={regionsVisible} onValueChange={setRegionsVisible} trackColor={{ false: theme.colors.border, true: theme.colors.rose }} />
      </View>
      {regionsVisible ? <View style={styles.regions}>
        {metric.regions.map(({ region, value }) => <View key={region} style={styles.region}>
          <Text style={styles.body}>{t(`report.region.${region}`)}</Text>
          <Text style={styles.regionValue}>{active === 'blemish' ? t(value === 1 ? 'skin.acneDetected' : 'skin.acneNotDetected') : t('skin.grade', { grade: value })}</Text>
        </View>)}
      </View> : null}
    </> : null}
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
  care: { color: theme.colors.rose, backgroundColor: theme.colors.roseSoft }, question: { fontSize: 13, lineHeight: 21, color: theme.colors.ink },
  switchRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 }, regions: { gap: 8 },
  region: { padding: 16, borderRadius: 12, backgroundColor: theme.colors.chip, flexDirection: 'row', justifyContent: 'space-between', gap: 12 },
  regionValue: { color: theme.colors.rose, fontSize: 14, fontWeight: '700' },
});
