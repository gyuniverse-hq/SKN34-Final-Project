import { Stack, useRouter } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { ScrollView, Share, StyleSheet, Text, View } from 'react-native';
import { Button } from '@/components/ui/Button';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';
import { skinAnalysisSupported } from '@/lib/skinAnalysis';
import { clearSkinTimings, comparableSkinTimings, readSkinTimings, summarizeSkinTimings } from '@/lib/skinProfile';
import type { SkinTiming } from '@/types/skin';

export default function SkinBenchmarkScreen() {
  const { t } = useI18n();
  const router = useRouter();
  const [rows, setRows] = useState<SkinTiming[]>([]);
  const [failed, setFailed] = useState(false);
  const load = useCallback(() => { void readSkinTimings().then(setRows).catch(() => setFailed(true)); }, []);
  useEffect(load, [load]);
  const comparable = comparableSkinTimings(rows);
  const first = comparable.filter((row, index) => row.firstInProcess && comparable.findIndex(r => r.processId === row.processId) === index);
  const repeat = comparable.filter(row => !row.firstInProcess);
  return <ScrollView contentContainerStyle={styles.content}>
    <Stack.Screen options={{ title: t('skin.benchmark') }} />
    {!skinAnalysisSupported ? <Text>{t('skin.unsupported')}</Text> : <>
      <Text style={styles.body}>{t('skin.benchmarkHelp')}</Text>
      {[first, repeat].map((group, index) => {
        const stats = summarizeSkinTimings(group);
        return <View key={index} style={styles.card}>
          <Text style={styles.title}>{t(index === 0 ? 'skin.firstRuns' : 'skin.repeatRuns', { count: group.length })}</Text>
          <Text>{stats ? t('skin.statistics', { ...stats, median: stats.median.toFixed(0), min: stats.min.toFixed(0), max: stats.max.toFixed(0) }) : t('skin.emptyTimings')}</Text>
        </View>;
      })}
      {comparable.map(row => <View key={row.runId} style={styles.card}>
        <Text selectable>{row.device} · {row.androidVersion} · {row.build}</Text>
        <Text selectable>{row.runtime}</Text>
        {row.startupMs !== undefined && <Text>{t('skin.startupTiming', { ms: row.startupMs.toFixed(0) })}</Text>}
        <Text selectable>{row.totalMs.toFixed(0)} ms · PSS {row.memoryPssKb === null ? t('skin.memoryUnavailable') : `${row.memoryPssKb} KB`} · {t(row.firstInProcess ? 'skin.processFirst' : 'skin.processRepeat')}</Text>
        {row.requestMs !== undefined && <Text>{t('skin.serverTiming', { request: row.requestMs.toFixed(0), server: row.serverMs?.toFixed(0) || '?' })}</Text>}
        {row.models.map(model => <Text selectable key={model.indicator}>{t('skin.timingRow', {
          indicator: model.indicator, load: model.loadMs.toFixed(0), prepare: model.preprocessingMs.toFixed(0), infer: model.inferenceMs.toFixed(0),
        })}</Text>)}
        {row.models.some(model => model.downloadMs !== undefined) && <Text>{t('skin.downloadTiming', {
          ms: row.models.reduce((sum, model) => sum + (model.downloadMs || 0), 0).toFixed(0),
        })}</Text>}
        {row.jpegFixtureMaxError !== undefined && <Text selectable>{t('skin.webPreprocessing', { error: row.jpegFixtureMaxError.toFixed(5) })}</Text>}
      </View>)}
      <Button label={t('skin.start')} onPress={() => router.push('/skin-analysis')} />
      <Button label={t('skin.exportTimings')} disabled={!rows.length} onPress={() => {
        void Share.share({ message: JSON.stringify({ schema: 'skin-timings-v1', rows }, null, 2) }).catch(() => setFailed(true));
      }} />
      <Button label={t('skin.clearTimings')} variant="secondary" onPress={() => {
        void clearSkinTimings().then(() => setRows([])).catch(() => setFailed(true));
      }} />
    </>}
    {failed && <Text accessibilityRole="alert">{t('skin.storageFailed')}</Text>}
  </ScrollView>;
}
const styles = StyleSheet.create({
  content: { padding: 20, gap: 18 }, card: { padding: 16, borderRadius: 16, backgroundColor: theme.colors.card, gap: 6 },
  title: { fontSize: 18, fontWeight: '700' }, body: { fontSize: 15, lineHeight: 23 },
});
