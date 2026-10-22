import { Stack } from 'expo-router';
import * as ImagePicker from 'expo-image-picker';
import { useCallback, useEffect, useState } from 'react';
import { Image, Pressable, ScrollView, Switch, Text, View } from 'react-native';
import { Button } from '@/components/ui/Button';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';
import { niaRequest } from '@/lib/nia';
import { useNiaPhotoProfile } from '@/hooks/useNiaPhotoProfile';
import { useNiaDashboard } from '@/hooks/useNiaDashboard';
import type { NiaInference, NiaJob, NiaStatus } from '@/types/nia';
import { NiaDashboard } from '@/components/nia/NiaDashboard';
import { NiaPhotoProfile } from '@/components/nia/NiaPhotoProfile';
import { Bars, Card, Field, Metrics, ModelDetails, ms, number, Runtime, styles } from '@/components/nia/NiaViews';

type Selection = { model_id: string; area: string; bbox: number[] };

export default function NiaEvaluationRoute() {
  const { t } = useI18n();
  return <>
    <Stack.Screen options={{ title: t('nia.title') }} />
    {__DEV__ ? <NiaResearchScreen /> : <Text accessibilityRole="alert">{t('nia.devOnly')}</Text>}
  </>;
}

function NiaResearchScreen() {
  const { t } = useI18n();
  const [status, setStatus] = useState<NiaStatus>();
  const [modelId, setModelId] = useState('');
  const [areaChoice, setArea] = useState('');
  const [tab, setTab] = useState<'profile' | 'single' | 'dataset'>('profile');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [image, setImage] = useState<ImagePicker.ImagePickerAsset>();
  const [bbox, setBbox] = useState(['', '', '', '']);
  const [roiConfirmed, setRoiConfirmed] = useState(false);
  const [repeats, setRepeats] = useState('10');
  const [sequence, setSequence] = useState<Selection[]>([]);
  const [inference, setInference] = useState<NiaInference>();
  const [transferMs, setTransferMs] = useState<number>();
  const [datasetRoot, setDatasetRoot] = useState('');
  const [testSplit, setTestSplit] = useState('');
  const [useLabels, setUseLabels] = useState(false);
  const [labelsDirectory, setLabelsDirectory] = useState('label');
  const [trainSplit, setTrainSplit] = useState('');
  const [valSplit, setValSplit] = useState('');
  const [metadataCsv, setMetadataCsv] = useState('');
  const [device, setDevice] = useState('');
  const [allAreas, setAllAreas] = useState(true);
  const [job, setJob] = useState<NiaJob>();
  const [history, setHistory] = useState<NiaJob[]>([]);
  const photoControls = useNiaPhotoProfile(status);
  const dashboardControls = useNiaDashboard(job?.id);
  const selected = status?.models.find(model => model.id === modelId);
  const area = selected?.areas[areaChoice] ? areaChoice : Object.keys(selected?.areas || {})[0] || '';
  const jobActive = job?.status === 'queued' || job?.status === 'running';

  const refresh = useCallback(async () => {
    const next = await niaRequest<NiaStatus>('status');
    setStatus(next);
    setModelId(previous => next.models.some(m => m.id === previous) ? previous : next.models[0]?.id || '');
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    niaRequest<NiaStatus>('status', undefined, controller.signal).then(next => {
      setStatus(next); setModelId(next.models[0]?.id || '');
    }).catch(e => { if (!controller.signal.aborted) setError(String(e)); });
    return () => controller.abort();
  }, []);

  const activeJobId = jobActive ? job?.id : undefined;
  useEffect(() => {
    if (!activeJobId) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const next = await niaRequest<NiaJob>(`job?id=${activeJobId}`, undefined, controller.signal);
        if (controller.signal.aborted) return;
        setJob(next);
        if (next.status === 'completed') setHistory(previous => [...previous.filter(j => j.id !== next.id), next].slice(-4));
        if (next.status === 'queued' || next.status === 'running') timer = setTimeout(poll, 1000);
      } catch (e) {
        if (!controller.signal.aborted) {
          setError(String(e));
          timer = setTimeout(poll, 5000);
        }
      }
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [activeJobId]);

  async function run(action: () => Promise<void>) {
    setBusy(true); setError('');
    try { await action(); } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }

  async function pick() {
    const result = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ['images'], base64: true, quality: 1 });
    if (result.canceled) return;
    const asset = result.assets[0];
    if (!asset.base64 || asset.base64.length > 16 * 1024 * 1024 || (asset.mimeType && !['image/jpeg', 'image/png'].includes(asset.mimeType))) {
      throw new Error(t('nia.invalidImage'));
    }
    setImage(asset); setBbox(['', '', '', '']); setSequence([]); setRoiConfirmed(false);
    setInference(undefined); setTransferMs(undefined);
  }

  function chooseModel(id: string) { setModelId(id); setRoiConfirmed(false); }
  const validBbox = bbox.every(v => v.trim() !== '' && Number.isFinite(Number(v))) && Number(bbox[0]) >= 0 && Number(bbox[1]) >= 0 && Number(bbox[2]) > Number(bbox[0]) && Number(bbox[3]) > Number(bbox[1]) && !!image && Number(bbox[2]) <= image.width && Number(bbox[3]) <= image.height;
  const currentSelection = { model_id: modelId, area, bbox: bbox.map(Number) };
  const canInfer = !!image && !!selected?.loaded && validBbox && roiConfirmed && !busy && !jobActive;

  return <ScrollView contentContainerStyle={styles.page} keyboardShouldPersistTaps="handled">
    <Card title={t('nia.title')}>
      <Text style={styles.body}>{t('nia.intro')}</Text>
      <Text style={styles.warning}>{t('nia.limitations')}</Text>
      <Text selectable style={styles.small}>{t('nia.setup')}</Text>
      <Button compact label={t('nia.refresh')} variant="secondary" disabled={busy} onPress={() => void run(refresh)} />
      {error ? <Text accessibilityRole="alert" style={styles.error}>{t('nia.error', { message: error })}</Text> : null}
    </Card>
    <View style={styles.wrap}>{(['profile', 'single', 'dataset'] as const).map(key => <Button key={key} label={t(key === 'profile' ? 'nia.photo.title' : `nia.${key}`)} variant={tab === key ? 'primary' : 'secondary'} onPress={() => setTab(key)} />)}</View>
    <View style={{ display: tab === 'profile' ? 'flex' : 'none', gap: 16 }}><NiaPhotoProfile status={status} controls={photoControls} /></View>
    {tab !== 'profile' ? <>
    <Card title={t('nia.model')}>
      {!status?.models.length ? <Text style={styles.warning}>{t('nia.noModels')}</Text> : null}
      {status?.models.map(model => <Pressable key={model.id} accessibilityRole="radio" accessibilityState={{ selected: model.id === modelId }} onPress={() => chooseModel(model.id)} style={{ padding: 12, borderRadius: 8, borderWidth: 1, borderColor: model.id === modelId ? theme.colors.rose : theme.colors.border }}>
        <Text style={styles.body}>{model.id} · {model.task}</Text>
        <Text style={styles.small}>{t(model.loaded ? 'nia.loaded' : model.present ? 'nia.configured' : 'nia.missing')}</Text>
      </Pressable>)}
      {Object.entries(status?.errors || {}).map(([key, value]) => <Text key={key} style={styles.error}>{key}: {value}</Text>)}
      {selected ? <>
        <Button label={t('nia.load')} disabled={!selected.present || busy || jobActive || selected.loaded} loading={busy} onPress={() => void run(async () => { await niaRequest('load', { model_id: modelId }); await refresh(); })} />
        {selected.metadata ? <ModelDetails model={selected.metadata} /> : null}
        <Text style={styles.body}>{t('nia.area')}</Text>
        <View style={styles.wrap}>{Object.keys(selected.areas).map(key => <Button key={key} compact label={areaName(key, t)} variant={area === key ? 'primary' : 'secondary'} onPress={() => { setArea(key); setRoiConfirmed(false); }} />)}</View>
      </> : null}
    </Card>
    {tab === 'single' ? <>
      <Card title={t('nia.single')}>
        <Button label={t('nia.pick')} variant="secondary" disabled={busy} onPress={() => void run(pick)} />
        {image ? <>
          <View style={{ width: '100%', aspectRatio: image.width / image.height, overflow: 'hidden' }}>
            <Image source={{ uri: image.uri }} accessibilityLabel={t('nia.image')} style={{ width: '100%', height: '100%' }} resizeMode="stretch" />
            {validBbox ? <View pointerEvents="none" style={{ position: 'absolute', borderWidth: 2, borderColor: theme.colors.rose, left: `${Number(bbox[0]) / image.width * 100}%`, top: `${Number(bbox[1]) / image.height * 100}%`, width: `${(Number(bbox[2]) - Number(bbox[0])) / image.width * 100}%`, height: `${(Number(bbox[3]) - Number(bbox[1])) / image.height * 100}%` }} /> : null}
          </View>
          <Text style={styles.small}>{image.width} × {image.height} px</Text>
          <Text style={styles.body}>{t('nia.roi')}</Text>
          <View style={styles.wrap}>{['x1', 'y1', 'x2', 'y2'].map((label, i) => <View key={label} style={{ minWidth: 64, flex: 1 }}><Field label={label} value={bbox[i]} numeric onChange={value => { setBbox(previous => previous.map((v, j) => j === i ? value : v)); setRoiConfirmed(false); }} /></View>)}</View>
          <Text style={styles.warning}>{t('nia.roiHint')}</Text>
          {selected?.areas[area]?.includes(0) ? <Text style={styles.warning}>{t('nia.fullFace')}</Text> : null}
          <View style={styles.row}><Switch accessibilityLabel={t('nia.confirmRoi')} value={roiConfirmed} disabled={!validBbox} onValueChange={setRoiConfirmed} /><Text style={[styles.body, { flex: 1 }]}>{t('nia.confirmRoi')}</Text></View>
          <Field label={t('nia.repeats')} numeric value={repeats} onChange={setRepeats} />
          <Button label={t('nia.addSequence')} variant="secondary" disabled={!canInfer || sequence.length >= 10} onPress={() => setSequence(previous => [...previous, currentSelection])} />
          {sequence.length ? <>
            <Text style={styles.body}>{t('nia.sequence', { count: sequence.length })}</Text>
            <Text selectable style={styles.mono}>{sequence.map(s => `${s.model_id} / ${s.area}: [${s.bbox.join(', ')}]`).join('\n')}</Text>
            <Button compact variant="ghost" label={t('nia.clearSequence')} onPress={() => setSequence([])} />
          </> : null}
        </> : null}
        <Button label={t('nia.run')} disabled={!canInfer} loading={busy} onPress={() => void run(async () => {
          setInference(undefined); setTransferMs(undefined);
          const tick = performance.now();
          const result = await niaRequest<NiaInference>('infer', { image: image!.base64, roi_confirmed: true, repeats: Number(repeats), selections: sequence.length ? sequence : [currentSelection] });
          setTransferMs(Math.max(0, performance.now() - tick - result.sequence_server_ms)); setInference(result);
        })} />
      </Card>
      {inference ? <Card title={t('nia.timing')}>
        <Text style={styles.body}>{t('nia.serverTime')}: {ms(inference.sequence_server_ms)}</Text>
        {transferMs !== undefined ? <Text style={styles.small}>{t('nia.upload', { ms: transferMs.toFixed(2) })}</Text> : null}
      </Card> : null}
      {inference?.results.map((result, i) => <Card key={i} title={`${result.model.id} / ${areaName(result.area, t)}`}>
        <ModelDetails model={result.model} />
        <Text style={styles.heading}>{result.mode === 'class' ? t('nia.grade', { value: result.prediction.grade! }) : t('nia.value', { value: number(result.prediction.value!), unit: result.prediction.unit! })}</Text>
        {result.prediction.probabilities ? <><Text style={styles.body}>{t('nia.probabilities')}</Text><Bars values={result.prediction.probabilities.map((p, grade) => ({ label: `${grade} (${(p * 100).toFixed(2)}%)`, value: p }))} /></> : null}
        <Text style={styles.body}>{t('nia.preprocessed')}</Text>
        {result.preprocessing.preview ? <Image source={{ uri: result.preprocessing.preview }} accessibilityLabel={t('nia.preprocessed')} style={{ width: 256, height: 256, maxWidth: '100%' }} /> : null}
        <Text style={styles.body}>{t('nia.rawPreprocessing')}</Text>
        <Text selectable style={styles.mono}>{JSON.stringify({ ...result.preprocessing, preview: undefined }, null, 2)}</Text>
        <Text style={styles.body}>{t('nia.preprocessing')}: {ms(result.preprocessing_ms)}</Text>
        <Runtime timing={result.inference} />
        <Text style={styles.body}>{t('nia.serverTime')}: {ms(result.server_ms)}</Text>
        <Text style={styles.body}>{t('nia.gpuPeakProcess')}: {result.gpu_peak_process_bytes === null ? t('nia.notAvailable') : `${(result.gpu_peak_process_bytes / 1048576).toFixed(1)} MiB`}</Text>
      </Card>)}
    </> : <>
      <Card title={t('nia.dataset')}>
        <Text style={styles.body}>{t('nia.dataHelp')}</Text>
        {!status?.dataset_configured ? <Text style={styles.warning}>{t('nia.noData')}</Text> : null}
        <Field label={t('nia.root')} value={datasetRoot} onChange={setDatasetRoot} />
        <View style={styles.row}><Switch accessibilityLabel={t('nia.useLabels')} value={useLabels} onValueChange={setUseLabels} /><Text style={[styles.body, { flex: 1 }]}>{t('nia.useLabels')}</Text></View>
        {useLabels ? <><Text style={styles.warning}>{t('nia.labelsWarning')}</Text><Field label={t('nia.labelsDirectory')} value={labelsDirectory} onChange={setLabelsDirectory} /></> : <Field label={t('nia.testSplit')} value={testSplit} onChange={setTestSplit} />}
        <Field label={t('nia.trainSplit')} value={trainSplit} onChange={setTrainSplit} />
        <Field label={t('nia.valSplit')} value={valSplit} onChange={setValSplit} />
        <Field label={t('nia.metadata')} value={metadataCsv} onChange={setMetadataCsv} />
        <View style={styles.row}><Switch accessibilityLabel={t('nia.all')} value={allAreas} onValueChange={setAllAreas} /><Text style={styles.body}>{t('nia.area')}: {t('nia.all')}</Text></View>
        <Text style={styles.body}>{t('nia.device')}</Text>
        <View style={styles.wrap}>{(['', 'DSLR', 'tablet', 'smartphone'] as const).map(key => <Button key={key} compact variant={device === key ? 'primary' : 'secondary'} label={t(key ? `nia.${key}` : 'nia.all')} onPress={() => setDevice(key)} />)}</View>
        <Button label={t('nia.evaluate')} disabled={!selected?.loaded || !status?.dataset_configured || !datasetRoot || !(useLabels ? labelsDirectory : testSplit) || busy || jobActive} loading={!!jobActive} onPress={() => void run(async () => {
          const next = await niaRequest<{ id: string }>('evaluate', { model_id: modelId, dataset_root: datasetRoot, test_split: useLabels ? undefined : testSplit, labels_directory: useLabels ? labelsDirectory : undefined, train_split: trainSplit || undefined, val_split: valSplit || undefined, metadata_csv: metadataCsv || undefined, device: device || undefined, areas: allAreas ? Object.keys(selected!.areas) : [area] });
          setJob({ id: next.id, status: 'queued', completed: 0, total: null, report: null });
        })} />
        {job ? <Text accessibilityLiveRegion="polite" style={styles.body}>{t('nia.progress', { status: t(`nia.${job.status}`), completed: job.completed, total: job.total ?? '…' })}</Text> : null}
        {job?.error ? <Text accessibilityRole="alert" style={styles.error}>{t('nia.error', { message: job.error })}</Text> : null}
      </Card>
      {history.length ? <Card title={t('nia.history')}>
        <Text style={styles.small}>{t('nia.historyHint')}</Text>
        {history.map(previous => previous.report ? <View key={previous.id} style={styles.field}>
          <Button compact variant="secondary" disabled={jobActive} label={`${previous.report.model.id} · ${previous.report.model.task} · n=${previous.report.metrics.n}`} onPress={() => setJob(previous)} />
          <Metrics metrics={previous.report.metrics} unit={previous.report.unit} />
        </View> : null)}
      </Card> : null}
      {job?.report ? <NiaDashboard key={job.id} report={job.report} controls={dashboardControls} previewsAllowed={!!status?.previews_allowed} /> : null}
    </>}
    </> : null}
  </ScrollView>;
}

function areaName(area: string, t: ReturnType<typeof useI18n>['t']) {
  const region = (['forehead', 'glabellus', 'perocular', 'cheek', 'chin'] as const).find(key => area.startsWith(`${key}_`));
  return region ? `${t(`nia.${region}`)} · ${area}` : area;
}
