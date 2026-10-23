import { Image, ScrollView, Text, View } from 'react-native';
import { Button } from '@/components/ui/Button';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';
import { getNiaAcneView } from '@/lib/niaPhoto';
import type { NiaPhotoControls, NiaPhotoFeature, NiaPhotoRow, NiaStatus } from '@/types/nia';
import { Bars, Card, ms, number, styles } from './NiaViews';

export function NiaPhotoProfile({ status, controls }: { status?: NiaStatus; controls: NiaPhotoControls }) {
  const { t } = useI18n();
  const { image, job, busy, error, details, setDetails } = controls;
  const active = job?.status === 'queued' || job?.status === 'running';
  const report = job?.report;
  const modelsPresent = status?.models.some(model => model.present) || status?.acne?.present;
  const acneView = getNiaAcneView(status, report);
  const acne = 'result' in acneView ? acneView.result : undefined;
  const outdated = acneView.status === 'outdated';

  return <>
    <Card title={t('nia.photo.title')}>
      <Text style={styles.body}>{t('nia.photo.intro')}</Text>
      <Text style={styles.warning}>{t('nia.photo.caution')}</Text>
      {status?.acne?.present ? <Text accessibilityLiveRegion="polite" style={styles.body}>{t('nia.acne.ready')}</Text> : null}
      <Button label={t('nia.pick')} variant="secondary" disabled={busy || active} onPress={() => void controls.pick()} />
      {image ? <View style={{ width: '100%', aspectRatio: image.width / image.height }}>
        <Image source={{ uri: image.uri }} accessibilityLabel={t('nia.image')} resizeMode="stretch" style={{ width: '100%', height: '100%' }} />
        {report ? Object.entries(report.roi.boxes).filter(([part]) => part !== '0').map(([part, box]) => <View key={part} pointerEvents="none" style={{ position: 'absolute', borderWidth: 1, borderColor: theme.colors.rose,
          left: `${box[0] / report.roi.original_size[0] * 100}%`, top: `${box[1] / report.roi.original_size[1] * 100}%`,
          width: `${(box[2] - box[0]) / report.roi.original_size[0] * 100}%`, height: `${(box[3] - box[1]) / report.roi.original_size[1] * 100}%` }} />) : null}
      </View> : null}
      <Button label={t('nia.photo.run')} loading={busy || active} disabled={!image || busy || active || !modelsPresent} onPress={() => void controls.analyze()} />
      {active ? <Text accessibilityLiveRegion="polite" style={styles.body}>{t('nia.photo.progress', { completed: job.completed, total: job.total ?? '…' })}</Text> : null}
      {error ? <Text accessibilityRole="alert" style={styles.error}>{t('nia.error', { message: error })}</Text> : null}
      {!modelsPresent ? <Text style={styles.warning}>{t('nia.noModels')}</Text> : null}
    </Card>
    {report ? <>
      <Card title={t('nia.photo.summary')}>
        <Text style={styles.heading}>{t('nia.photo.coverage', { count: report.predicted, total: report.expected })}</Text>
        <Text style={styles.small}>{t('nia.serverTime')}: {ms(report.server_ms)}</Text>
        {report.status !== 'complete' ? <Text style={styles.warning}>{t('nia.photo.partial')}</Text> : null}
        {(Object.entries(report.groups) as [NiaPhotoFeature, typeof report.groups[NiaPhotoFeature]][]).map(([feature, group]) => <View key={feature} style={styles.field}>
          <Text style={styles.heading}>{t(`nia.photo.${feature}`)}</Text>
          {feature === 'dryness' ? <Text style={styles.small}>{t('nia.photo.lipDryness')}</Text> : null}
          {group.rows.map(row => <View key={row.key} style={[styles.row, { justifyContent: 'space-between', alignItems: 'flex-start' }]}>
            <Text style={[styles.body, { flex: 1 }]}>{t(`nia.photo.region.${row.region}`)}</Text>
            <Text selectable style={[styles.body, { flex: 1, textAlign: 'right' }]}>{row.value === null ? t(row.status === 'failed' ? 'nia.photo.failed' : 'nia.photo.unavailable') : row.result?.mode === 'class' ? t('nia.photo.gradeScale', { grade: row.value, max: row.result.model.outputs - 1 }) : number(row.value)}</Text>
          </View>)}
          {group.task.startsWith('regression/') ? <Text style={styles.small}>{t('nia.photo.unitUnconfirmed')}</Text> : null}
        </View>)}
        <View style={styles.field}>
          <Text style={styles.heading}>{t('nia.photo.acne')}</Text>
          {acne ? <>
            <Text style={styles.body}>{acne.status === 'predicted' ? t(acne.label === 1 ? 'nia.acne.positive' : 'nia.acne.negative') : t('nia.photo.failed')}</Text>
            {acne.score !== null ? <Text style={styles.small}>{t('nia.acne.score', { score: number(acne.score), threshold: number(acne.threshold ?? 0.5) })}</Text> : null}
            <Text style={styles.warning}>{t('nia.acne.caution')}</Text>
            {acne.error ? <Text style={styles.error}>{acne.error}</Text> : null}
          </> : outdated ? <>
            <Text accessibilityLiveRegion="polite" style={styles.warning}>{t('nia.acne.outdated')}</Text>
            <Button compact label={t('nia.acne.reanalyze')} disabled={!image || busy || active} onPress={() => void controls.analyze()} />
          </> : <Text style={styles.small}>{t('nia.photo.unsupported')}</Text>}
        </View>
        {(['oiliness', 'skin_type'] as const).map(key => <View key={key} style={styles.row}>
          <Text style={[styles.body, { flex: 1 }]}>{t(`nia.photo.${key}`)}</Text><Text style={styles.small}>{t('nia.photo.unsupported')}</Text>
        </View>)}
      </Card>
      <Card title={t('nia.photo.json')}>
        <Text style={styles.body}>{t('nia.photo.jsonHelp')}</Text>
        <Button label={t('nia.photo.export')} variant="secondary" disabled={busy || outdated} onPress={() => void controls.exportJson()} />
        <ScrollView horizontal><Text selectable style={styles.mono}>{JSON.stringify(report.ml_input.features, null, 2)}</Text></ScrollView>
      </Card>
      <Card title={t('nia.details')}>
        <Button label={t('nia.photo.toggleDetails')} variant="ghost" onPress={() => setDetails(!details)} />
        {details ? Object.values(report.groups).flatMap(group => group.rows).map(row => <PhotoDetail key={row.key} row={row} />) : null}
      </Card>
    </> : null}
  </>;
}

function PhotoDetail({ row }: { row: NiaPhotoRow }) {
  const { t } = useI18n();
  return <View style={styles.field}>
    <Text selectable style={styles.body}>{row.key}</Text>
    {row.error ? <Text style={styles.error}>{row.error}</Text> : null}
    {row.result ? <>
      {row.result.preprocessing.preview ? <Image source={{ uri: row.result.preprocessing.preview }} accessibilityLabel={`${t('nia.preprocessed')} · ${row.key}`} style={{ width: 160, height: 160 }} /> : null}
      {row.result.prediction.probabilities ? <><Text style={styles.small}>{t('nia.probabilities')}</Text><Bars values={row.result.prediction.probabilities.map((p, grade) => ({ label: String(grade), value: p }))} /></> : null}
      <Text selectable style={styles.mono}>{JSON.stringify({ prediction: row.result.prediction, crop: row.result.preprocessing.crop, checkpoint_sha256: row.result.model.sha256 }, null, 2)}</Text>
    </> : null}
  </View>;
}
