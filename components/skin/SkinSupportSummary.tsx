import { useState } from 'react';
import { Pressable, Text, View, StyleSheet } from 'react-native';
import { SUPPORT_QUESTIONS } from '@/constants/skinSurvey';
import { theme } from '@/constants/theme';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import type { SkinReport } from '@/types/skinReport';

export function SkinSupportSummary({ assessment }: { assessment: NonNullable<SkinReport['supportAssessment']> }) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(false);
  const { raw, questionnaire: q, fusion } = assessment;
  return <View style={styles.content}>
    {fusion && raw && <Text style={styles.body}>{t('support.imageType', { type: t(`report.type.${raw.label}`) })}</Text>}
    {fusion && <>
      <Text style={styles.body}>{t('support.fusionReason', { reason: t(`support.reason.${fusion.reason}`) })}</Text>
      <Text style={styles.body}>{t('support.fusionNotice')}</Text>
    </>}
    <Text style={styles.body}>{t('support.summary')}</Text>
    {SUPPORT_QUESTIONS.map(key => <View key={key} style={styles.content}>
      <Text style={styles.body}>{t(`support.${key}`)}</Text>
      <Text style={styles.body}>{t(`support.${key}.${q[key]}` as TranslationKey)}</Text>
    </View>)}
    <Text style={styles.body}>{t('support.priorityAnswer', { concern: t(`concern.${q.priority}`) })}</Text>
    <Text style={styles.body}>{t('support.careNote')}</Text>
    {raw && <>
      <Pressable accessibilityRole="button" accessibilityState={{ expanded }} onPress={() => setExpanded(!expanded)} style={styles.button}>
        <Text style={styles.link}>{t('support.modelScores')}</Text>
      </Pressable>
      {expanded && <View style={styles.content}>
        <Text style={styles.body}>{t(fusion ? 'support.fusionNotice' : 'support.scoreNotice')}</Text>
        {(['dry', 'balanced', 'oily'] as const).map((type, i) => <Text key={type} style={styles.body}>
          {fusion?.scores ? t('support.fusionScore', { type: t(`report.type.${type}`), raw: raw.probabilities[i].toFixed(3), score: fusion.scores[i].toFixed(3), delta: fusion.delta![i].toFixed(3) })
            : t('support.score', { type: t(`report.type.${type}`), score: raw.probabilities[i].toFixed(3) })}
        </Text>)}
      </View>}
    </>}
  </View>;
}
const styles = StyleSheet.create({
  content: { gap: 10 }, body: { fontSize: 13, lineHeight: 21, color: theme.colors.inkMuted },
  button: { minHeight: theme.hitTarget, justifyContent: 'center' }, link: { color: theme.colors.rose, fontWeight: '700' },
});
