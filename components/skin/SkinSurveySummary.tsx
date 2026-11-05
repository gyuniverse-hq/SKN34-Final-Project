import { useState } from 'react';
import { Pressable, Text, View, StyleSheet } from 'react-native';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';
import type { SkinReport } from '@/types/skinReport';

export function SkinSurveySummary({ assessment }: { assessment: NonNullable<SkinReport['assessment']> }) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(false);
  const { fusion, raw, questionnaire: q } = assessment;
  return <View style={styles.content}>
    <Text style={styles.body}>{t('survey.basis', { type: t(`report.type.${raw?.label ?? 'unknown'}`), score: fusion.sosTotal })}</Text>
    <Text style={styles.body}>{t('survey.adjustment', { reason: t(`survey.reason.${fusion.reason}`) })}</Text>
    <Text style={styles.body}>{t('survey.redBumpsAnswer', { answer: t(`survey.redBumps.${q.redBumps}`) })}</Text>
    <Text style={styles.body}>{t('survey.reactionAnswer', { answer: t(`survey.cosmeticReaction.${q.cosmeticReaction}`) })}</Text>
    <Text style={styles.body}>{t('survey.selectedPriority', { concern: t(`concern.${q.priority}`) })}</Text>
    <Pressable accessibilityRole="button" accessibilityState={{ expanded }} onPress={() => setExpanded(!expanded)} style={styles.button}>
      <Text style={styles.link}>{t('survey.compare')}</Text>
    </Pressable>
    {expanded && <View style={styles.content}>
      <Text style={styles.body}>{t('survey.scoreNotice', { policy: fusion.policy })}</Text>
      {raw && fusion.scores && fusion.delta && (['dry', 'balanced', 'oily'] as const).map((label, i) => <Text key={label} style={styles.body}>
        {t('survey.score', { type: t(`report.type.${label}`), raw: raw.probabilities[i].toFixed(3),
          score: fusion.scores![i].toFixed(3), delta: fusion.delta![i].toFixed(3) })}
      </Text>)}
    </View>}
  </View>;
}
const styles = StyleSheet.create({
  content: { gap: 10 }, body: { fontSize: 13, lineHeight: 21, color: theme.colors.inkMuted },
  button: { minHeight: theme.hitTarget, justifyContent: 'center' }, link: { color: theme.colors.rose, fontWeight: '700' },
});
