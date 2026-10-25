import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { Button } from '@/components/ui/Button';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';
import { summarizeSkinResult } from '@/lib/skinResult';
import type { SkinAnalysisResult } from '@/types/skin';

export function SkinResult({ result, onRecommend, onRetry, onExit }: {
  result: SkinAnalysisResult;
  onRecommend: () => void;
  onRetry: () => void;
  onExit: () => void;
}) {
  const { t } = useI18n();
  const summary = summarizeSkinResult(result.features);
  return <ScrollView contentContainerStyle={styles.content}>
    <Text accessibilityRole="header" style={styles.title}>{t('skin.resultTitle')}</Text>
    <Text accessibilityLiveRegion="polite" style={styles.help}>{t('skin.resultSaved')}</Text>
    <View style={styles.cards}>
      {summary.grades.map(({ indicator, grade, status }) => <View key={indicator} style={styles.card}>
        <Text style={styles.label}>{t(`skin.metric.${indicator}`)}</Text>
        <View style={styles.row}>
          <Text style={styles.grade}>{t('skin.grade', { grade })}</Text>
          <Text style={[styles.status, status === 'good' ? styles.good : styles.care]}>{t(`skin.status.${status}`)}</Text>
        </View>
      </View>)}
      <View style={styles.card}>
        <Text style={styles.label}>{t('skin.metric.acne')}</Text>
        <Text style={styles.grade}>{t(summary.acneDetected ? 'skin.acneDetected' : 'skin.acneNotDetected')}</Text>
      </View>
    </View>
    <Text style={styles.help}>{t('skin.gradeHelp')}</Text>
    <View style={styles.actions}>
      <Button label={t('skin.recommend')} icon="sparkles-outline" onPress={onRecommend} />
      <Button variant="secondary" label={t('skin.restart')} onPress={onRetry} />
      <Button variant="ghost" label={t('skin.exit')} onPress={onExit} />
    </View>
  </ScrollView>;
}

const styles = StyleSheet.create({
  content: { paddingVertical: 16, gap: 16 },
  title: { fontSize: 24, fontWeight: '700', color: theme.colors.ink },
  help: { fontSize: 14, lineHeight: 21, color: theme.colors.inkMuted },
  cards: { gap: 12 },
  card: { padding: 18, gap: 12, borderRadius: theme.radius.lg, backgroundColor: theme.colors.surfaceAlt },
  label: { fontSize: 16, fontWeight: '600', color: theme.colors.ink },
  row: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 12 },
  grade: { fontSize: 20, fontWeight: '700', color: theme.colors.ink },
  status: { fontSize: 15, fontWeight: '600', paddingHorizontal: 12, paddingVertical: 6, borderRadius: theme.radius.pill },
  good: { color: theme.colors.success, backgroundColor: theme.colors.surface },
  care: { color: theme.colors.warning, backgroundColor: theme.colors.warningBg },
  actions: { gap: 10 },
});
