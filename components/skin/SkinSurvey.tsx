import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { Button } from '@/components/ui/Button';
import { Chip } from '@/components/ui/Chip';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';
import type { SkinAnswer, SkinQuestionnaire } from '@/types/skin';

export function SkinSurvey({ answers, onChange, onFinish, complete, saving, error }: {
  answers: Partial<SkinQuestionnaire>;
  onChange: (answers: Partial<SkinQuestionnaire>) => void;
  onFinish: () => void; complete: boolean; saving: boolean; error: boolean;
}) {
  const { t } = useI18n();
  return <ScrollView contentContainerStyle={styles.content}>
    <Text style={styles.title}>{t('skin.surveyTitle')}</Text>
    {(['tightness', 'oiliness', 'sensitivity'] as const).map(key => <View key={key} style={styles.question}>
      <Text style={styles.label}>{t(`skin.question.${key}`)}</Text>
      <View style={styles.options}>{([0, 1, 2, 'unknown'] as SkinAnswer[]).map(answer =>
        <Chip key={answer} label={answer === 'unknown' ? t('skin.unknown') : t(`skin.answer.${key === 'oiliness' ? 'oil' : 'frequency'}.${answer}`)}
          selected={answers[key] === answer} onPress={() => { if (!saving) onChange({ ...answers, [key]: answer }); }} />,
      )}</View>
    </View>)}
    {error && <Text accessibilityRole="alert" style={styles.error}>{t('skin.storageFailed')}</Text>}
    <Button label={t('skin.save')} onPress={onFinish} disabled={!complete} loading={saving} />
  </ScrollView>;
}
const styles = StyleSheet.create({
  content: { paddingVertical: 24, gap: 28 }, title: { fontSize: 24, fontWeight: '700', color: theme.colors.ink },
  question: { gap: 12 }, label: { fontSize: 17, color: theme.colors.ink, fontWeight: '600' },
  options: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 }, error: { color: theme.colors.danger },
});
