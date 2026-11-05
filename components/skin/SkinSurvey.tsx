import { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Button } from '@/components/ui/Button';
import { theme } from '@/constants/theme';
import { SUPPORT_QUESTIONS, SUPPORT_CHOICES, SUPPORT_REACTION_CHOICES, SUPPORT_PRIORITY_CONCERNS } from '@/constants/skinSurvey';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import type { SkinSurveyV3 } from '@/types/skin';

export function SkinSurvey({ answers, onChange, onFinish, complete, saving, error }: {
  answers: Partial<SkinSurveyV3>; onChange: (answers: Partial<SkinSurveyV3>) => void;
  onFinish: () => void; complete: boolean; saving: boolean; error: boolean;
}) {
  const { t } = useI18n();
  const [step, setStep] = useState(0);
  const total = SUPPORT_QUESTIONS.length + 1;
  const key = step < SUPPORT_QUESTIONS.length ? SUPPORT_QUESTIONS[step] : 'priority';
  const options: readonly string[] = key === 'priority' ? SUPPORT_PRIORITY_CONCERNS
    : key === 'cosmeticReaction' ? SUPPORT_REACTION_CHOICES : SUPPORT_CHOICES[key];
  const selected = answers[key];
  return <View style={styles.screen}>
    <View style={styles.progress} accessibilityRole="progressbar" accessibilityValue={{ min: 1, max: total, now: step + 1 }}>
      {Array.from({ length: total }, (_, i) => <View key={i} style={[styles.segment, i <= step && styles.segmentActive]} />)}
    </View>
    <ScrollView key={step} style={styles.scroll} contentContainerStyle={styles.content}>
      <View style={styles.number}><Text style={styles.numberText}>{step + 1}</Text></View>
      <Text style={styles.label} accessibilityRole="header">{key === 'priority' ? t('support.priority') : t(`support.${key}`)}</Text>
      {step === 0 && <Text style={styles.notice}>{t('support.notice')}</Text>}
      <View accessibilityRole="radiogroup" style={styles.options}>
        {options.map(answer => {
          const isSelected = selected === answer;
          const label = key === 'priority' ? t(`support.priorityChoice.${answer}` as TranslationKey) : t(`support.${key}.${answer}` as TranslationKey);
          return <Pressable key={answer} accessibilityRole="radio" accessibilityState={{ checked: isSelected, disabled: saving }}
            accessibilityLabel={label} disabled={saving} onPress={() => onChange({ ...answers, [key]: answer })}
            style={[styles.option, isSelected && styles.optionSelected]}>
            <View style={[styles.radio, isSelected && styles.radioSelected]}>{isSelected && <View style={styles.radioDot} />}</View>
            <Text style={[styles.optionText, isSelected && styles.optionTextSelected]}>{label}</Text>
          </Pressable>;
        })}
      </View>
      {error && <Text accessibilityRole="alert" style={styles.error}>{t('skin.storageFailed')}</Text>}
    </ScrollView>
    <View style={styles.footer}>
      <Button label={t('support.previous')} variant="secondary" disabled={step === 0 || saving} onPress={() => setStep(step - 1)} style={styles.previous} />
      <Button label={step === total - 1 ? t('skin.viewResult') : t('support.next')} loading={saving}
        disabled={saving || selected === undefined || (step === total - 1 && !complete)}
        onPress={() => { if (step === total - 1) onFinish(); else setStep(step + 1); }} style={styles.next} />
    </View>
  </View>;
}
const styles = StyleSheet.create({
  screen: { flex: 1, gap: 18 }, progress: { flexDirection: 'row', gap: 6, paddingTop: 8 },
  segment: { flex: 1, height: 5, borderRadius: 4, backgroundColor: theme.colors.border },
  segmentActive: { backgroundColor: theme.colors.rose }, scroll: { flex: 1 },
  content: { paddingTop: 22, paddingBottom: 24, gap: 20 },
  number: { width: 42, height: 42, borderRadius: 14, alignItems: 'center', justifyContent: 'center', backgroundColor: theme.colors.roseSoft },
  numberText: { color: theme.colors.rose, fontSize: 16, fontWeight: '800' },
  label: { fontSize: 23, lineHeight: 34, color: theme.colors.ink, fontWeight: '800' },
  notice: { color: theme.colors.inkMuted, fontSize: 13, lineHeight: 20 },
  options: { gap: 8, marginTop: 8 },
  option: { minHeight: 56, padding: 14, flexDirection: 'row', alignItems: 'center', gap: 14, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.colors.border, backgroundColor: theme.colors.card },
  optionSelected: { borderColor: theme.colors.rose, backgroundColor: theme.colors.roseSoft },
  radio: { width: 22, height: 22, borderRadius: 11, borderWidth: 2, borderColor: theme.colors.inkFaint, alignItems: 'center', justifyContent: 'center' },
  radioSelected: { borderColor: theme.colors.rose }, radioDot: { width: 10, height: 10, borderRadius: 5, backgroundColor: theme.colors.rose },
  optionText: { flex: 1, color: theme.colors.ink, fontSize: 15, lineHeight: 22 }, optionTextSelected: { color: theme.colors.rose, fontWeight: '700' },
  footer: { flexDirection: 'row', gap: 10 }, previous: { flex: 1 }, next: { flex: 2 }, error: { color: theme.colors.danger },
});
