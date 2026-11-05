import { Image, Text, View } from 'react-native';
import { Button } from '@/components/ui/Button';
import { useI18n } from '@/lib/i18n';
import type { NiaDashboardControls, NiaReport } from '@/types/nia';
import { Bars, Card, Confusion, extent, Metrics, ModelDetails, number, Runtime, Scatter, styles } from './NiaViews';

export function NiaDashboard({ report, previewsAllowed, controls }: { report: NiaReport; previewsAllowed: boolean; controls: NiaDashboardControls }) {
  const { t } = useI18n();
  const { preview, error } = controls;
  const samples = report.timing.samples_ms;
  const [low, high] = extent(samples);
  const width = (high - low) / 8 || 1;
  const histogram = Array.from({ length: 8 }, (_, i) => ({
    label: `${(low + i * width).toFixed(1)}–${(low + (i + 1) * width).toFixed(1)} ms`,
    value: samples.filter(v => Math.min(7, Math.floor((v - low) / width)) === i).length,
  }));
  const worst = report.samples.map((sample, index) => ({ ...sample, index })).sort((a, b) => b.error - a.error).slice(0, 20);
  return <>
    <Card title={t('nia.summary', { count: report.metrics.n })}>
      <Text style={styles.warning}>{t(report.dataset.leakage.status === 'overlap' ? 'nia.leakOverlap' : report.dataset.leakage.status === 'no_overlap' ? 'nia.leakClear' : 'nia.leakUnverified')}</Text>
      <Text selectable style={styles.mono}>{JSON.stringify(report.dataset.leakage.comparisons)}</Text>
      <ModelDetails model={report.model} />
      <Metrics metrics={report.metrics} unit={report.unit} />
      <Text style={styles.small}>{t('nia.limitations')}</Text>
      <View style={styles.wrap}>
        <Button label={t('nia.exportJson')} compact onPress={() => void controls.exportReport('json')} />
        <Button label={t('nia.exportCsv')} compact variant="secondary" onPress={() => void controls.exportReport('csv')} />
      </View>
      {error ? <Text accessibilityRole="alert" style={styles.error}>{t('nia.error', { message: error })}</Text> : null}
    </Card>
    {report.metrics.confusion ? <Card title={t('nia.confusion')}><Confusion matrix={report.metrics.confusion} /></Card> : null}
    {report.metrics.per_grade ? <>
      <Card title={t('nia.distribution')}><Bars values={report.metrics.per_grade.map(g => ({ label: String(g.grade), value: g.support, secondary: g.predicted }))} /></Card>
      <Card title={t('nia.perGrade')}>{report.metrics.per_grade.map(g => <Text key={g.grade} style={styles.mono}>{g.grade} · {number(g.precision)} / {number(g.recall)} / {number(g.f1)} · n={g.support}</Text>)}</Card>
    </> : null}
    {report.metrics.truth && report.metrics.predicted ? <>
      <Card title={t('nia.scatter')}><Scatter truth={report.metrics.truth} predicted={report.metrics.predicted} /></Card>
      <Card title={t('nia.valueDistribution')}><Bars values={regressionHistogram(report.metrics.truth, report.metrics.predicted)} /></Card>
    </> : null}
    {(['area', 'device', 'age_group', 'skin_tone', 'population'] as const).map(key => report.groups[key] ? <Card key={key} title={t(key === 'area' ? 'nia.areaComparison' : key === 'device' ? 'nia.deviceComparison' : `nia.${key}`)}>
      {Object.entries(report.groups[key]).map(([value, metrics]) => <View key={value} style={styles.field}>
        <Text style={styles.body}>{value} · n={metrics.n}</Text><Metrics metrics={metrics} unit={report.unit} />
      </View>)}
    </Card> : null)}
    <Card title={t('nia.latency')}>
      <Runtime timing={report.timing} /><Bars values={histogram} />
      <Text style={styles.body}>{t('nia.preprocessing')}</Text><Runtime timing={report.preprocessing} />
      <Text style={styles.body}>{t('nia.serverTime')}</Text><Runtime timing={report.sample_server} />
      <Text style={styles.body}>{number(report.server_ms)} ms</Text>
      <Text style={styles.small}>{t('nia.gpuPeakProcess')}: {report.gpu_peak_process_bytes === null ? t('nia.notAvailable') : `${(report.gpu_peak_process_bytes / 1048576).toFixed(1)} MiB`}</Text>
    </Card>
    <Card title={t('nia.errors')}>
      {!previewsAllowed ? <Text style={styles.small}>{t('nia.previewBlocked')}</Text> : null}
      {worst.map(sample => <View key={`${sample.area}-${sample.index}`} style={styles.field}>
        <Text selectable style={styles.mono}>{sample.id} · {sample.area} · {sample.device}</Text>
        <Text style={styles.body}>{number(sample.truth)} / {number(sample.prediction)} / {number(sample.error)} {report.unit || ''}</Text>
        {previewsAllowed ? <Button compact variant="secondary" label={t('nia.preview')} onPress={() => void controls.showSample(sample.index)} /> : null}
        {preview?.index === sample.index ? <Image source={{ uri: preview.uri }} accessibilityLabel={t('nia.preprocessed')} style={{ width: 256, height: 256, maxWidth: '100%' }} /> : null}
      </View>)}
    </Card>
  </>;
}

function regressionHistogram(truth: number[], predicted: number[]) {
  const [low, high] = extent([...truth, ...predicted]);
  const width = (high - low) / 8 || 1;
  return Array.from({ length: 8 }, (_, i) => ({
    label: `${(low + i * width).toFixed(2)}–${(low + (i + 1) * width).toFixed(2)}`,
    value: truth.filter(v => Math.min(7, Math.floor((v - low) / width)) === i).length,
    secondary: predicted.filter(v => Math.min(7, Math.floor((v - low) / width)) === i).length,
  }));
}
