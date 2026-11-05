import type { PropsWithChildren } from 'react';
import { ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';
import type { NiaMetrics, NiaModelMetadata, NiaTiming } from '@/types/nia';

export const ms = (value: number) => `${value.toFixed(2)} ms`;
export const percent = (value: number) => `${(value * 100).toFixed(2)}%`;
export const number = (value: number) => Number.isInteger(value) ? String(value) : value.toFixed(3);
export function extent(values: number[]) {
  return values.reduce(([low, high], value) => [Math.min(low, value), Math.max(high, value)], [Infinity, -Infinity]);
}

export function Card({ title, children }: PropsWithChildren<{ title?: string }>) {
  return <View style={styles.card}>
    {title ? <Text style={styles.heading}>{title}</Text> : null}
    {children}
  </View>;
}

export function Field({ label, value, onChange, numeric = false }: {
  label: string; value: string; onChange: (value: string) => void; numeric?: boolean;
}) {
  return <View style={styles.field}>
    <Text style={styles.body}>{label}</Text>
    <TextInput accessibilityLabel={label} value={value} onChangeText={onChange}
      autoCapitalize="none" autoCorrect={false} keyboardType={numeric ? 'numeric' : 'default'}
      style={styles.input} />
  </View>;
}

export function Bars({ values }: { values: { label: string; value: number; secondary?: number }[] }) {
  const maximum = Math.max(1, ...values.flatMap(v => [v.value, v.secondary || 0]));
  return <View style={styles.field}>{values.map((v, index) => <View key={`${v.label}-${index}`} style={styles.field}>
    <Text style={styles.small}>{v.label} · {number(v.value)}{v.secondary !== undefined ? ` / ${number(v.secondary)}` : ''}</Text>
    <View style={styles.track}><View style={[styles.bar, { width: `${v.value / maximum * 100}%` }]} /></View>
    {v.secondary !== undefined ? <View style={styles.track}><View style={[styles.bar, { backgroundColor: theme.colors.inkMuted, width: `${v.secondary / maximum * 100}%` }]} /></View> : null}
  </View>)}</View>;
}

export function Runtime({ timing }: { timing: NiaTiming }) {
  return <Text selectable style={styles.mono}>
    {`n=${timing.n} · Mean ${ms(timing.mean_ms)} · P50 ${ms(timing.p50_ms)} · P95 ${ms(timing.p95_ms)}`}
  </Text>;
}

export function ModelDetails({ model }: { model: NiaModelMetadata }) {
  const { t } = useI18n();
  return <View style={styles.field}>
    <Text selectable style={styles.mono}>{model.id} · {model.task} · {model.architecture} · {model.device}{model.gpu ? ` (${model.gpu})` : ''}</Text>
    <Text style={styles.body}>{t('nia.loadTime')}: {ms(model.load_ms)} · {t('nia.warmup')}: {ms(model.warmup_ms)}</Text>
    <Text style={styles.body}>{t('nia.gpuResident')}: {model.gpu_resident_bytes === null ? t('nia.notAvailable') : `${(model.gpu_resident_bytes / 1048576).toFixed(1)} MiB`}</Text>
    <Text selectable style={styles.mono}>{model.checkpoint}{'\n'}SHA-256: {model.sha256}{'\n'}NIA: {model.source_commit}{'\n'}{JSON.stringify(model.libraries)}</Text>
  </View>;
}

export function Metrics({ metrics, unit }: { metrics: NiaMetrics; unit?: string }) {
  const { t } = useI18n();
  return <View style={styles.metrics}>
    {[
      ['Accuracy', metrics.accuracy === undefined ? undefined : percent(metrics.accuracy)],
      ['MAE', `${number(metrics.mae)}${unit ? ` ${unit}` : ''}`],
      ['±1 Grade Accuracy', metrics.within_one === undefined ? undefined : percent(metrics.within_one)],
      ['Macro F1', metrics.macro_f1 === undefined ? undefined : number(metrics.macro_f1)],
      ['RMSE', metrics.rmse === undefined ? undefined : `${number(metrics.rmse)} ${unit || ''}`],
      ['Pearson r', metrics.pearson === undefined ? undefined : metrics.pearson === null ? t('nia.notAvailable') : number(metrics.pearson)],
    ].filter(([, value]) => value !== undefined).map(([label, value]) => <View key={label} style={styles.metric}>
      <Text style={styles.small}>{label}</Text><Text style={styles.heading}>{value}</Text>
    </View>)}
  </View>;
}

export function Confusion({ matrix }: { matrix: number[][] }) {
  const maximum = Math.max(1, ...matrix.flat());
  return <ScrollView horizontal>
    <View>
      <View style={styles.row}><Text style={styles.cell}>↓ / →</Text>{matrix.map((_, i) => <Text key={i} style={styles.cell}>{i}</Text>)}</View>
      {matrix.map((row, i) => <View key={i} style={styles.row}>
        <Text style={styles.cell}>{i}</Text>
        {row.map((value, j) => <Text key={j} style={[styles.cell, { backgroundColor: `rgba(194,71,94,${.06 + value / maximum * .5})` }]}>{value}</Text>)}
      </View>)}
    </View>
  </ScrollView>;
}

export function Scatter({ truth, predicted }: { truth: number[]; predicted: number[] }) {
  const { t } = useI18n();
  const [minimum, maximum] = extent([...truth, ...predicted]);
  const span = maximum - minimum || 1;
  // Limit rendered markers for mobile performance; all values remain in the JSON report.
  const stride = Math.max(1, Math.ceil(truth.length / 300));
  return <View style={styles.field}>
    <View accessibilityRole="image" accessibilityLabel={t('nia.axes')} style={styles.scatter}>
      {truth.map((value, index) => index % stride === 0 ? <View key={index} style={[styles.dot, {
        left: `${(value - minimum) / span * 96}%`, bottom: `${(predicted[index] - minimum) / span * 96}%`,
      }]} /> : null)}
    </View>
    <Text style={styles.small}>x / y: {number(minimum)} – {number(maximum)} · n={truth.length}</Text>
  </View>;
}

export const styles = StyleSheet.create({
  page: { padding: 16, gap: 16, maxWidth: 1040, width: '100%', alignSelf: 'center', paddingBottom: 48 },
  card: { backgroundColor: theme.colors.card, borderWidth: 1, borderColor: theme.colors.border, borderRadius: 16, padding: 16, gap: 14 },
  heading: { color: theme.colors.ink, fontSize: 18, fontWeight: '700' },
  body: { color: theme.colors.ink, fontSize: 14, lineHeight: 21 },
  small: { color: theme.colors.inkMuted, fontSize: 12, lineHeight: 18 },
  mono: { color: theme.colors.inkMuted, fontSize: 12, lineHeight: 19 },
  warning: { color: theme.colors.warning, backgroundColor: theme.colors.warningBg, padding: 12, borderRadius: 8, lineHeight: 21 },
  error: { color: theme.colors.danger, lineHeight: 21 },
  field: { gap: 6 },
  input: { minHeight: 46, borderWidth: 1, borderColor: theme.colors.border, borderRadius: 8, padding: 10, color: theme.colors.ink },
  row: { flexDirection: 'row', gap: 6, alignItems: 'center' },
  wrap: { flexDirection: 'row', gap: 8, flexWrap: 'wrap' },
  metrics: { flexDirection: 'row', gap: 12, flexWrap: 'wrap' },
  metric: { minWidth: 120, flexGrow: 1, padding: 12, backgroundColor: theme.colors.surfaceAlt, borderRadius: 8, gap: 8 },
  track: { height: 7, backgroundColor: theme.colors.surfaceAlt, borderRadius: 4, overflow: 'hidden' },
  bar: { height: 7, backgroundColor: theme.colors.rose, borderRadius: 4 },
  cell: { width: 40, minHeight: 36, textAlign: 'center', padding: 8, color: theme.colors.ink },
  scatter: { width: '100%', height: 200, borderLeftWidth: 1, borderBottomWidth: 1, borderColor: theme.colors.inkMuted },
  dot: { position: 'absolute', width: 5, height: 5, borderRadius: 3, backgroundColor: theme.colors.rose, opacity: .65 },
});
