import Ionicons from '@expo/vector-icons/Ionicons';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { theme } from '@/constants/theme';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import type { SkinConcern } from '@/types';
import type { CareIngredient } from '@/types/skinReport';
import { SkinConcernRail } from './SkinReportDetail';

export function SkinSolution({ concerns, active, onChange, ingredients }: {
  concerns: readonly SkinConcern[]; active: SkinConcern; onChange: (c: SkinConcern) => void; ingredients: readonly CareIngredient[];
}) {
  const { t } = useI18n();
  return <View>
    <View style={styles.section}>
      <Text style={styles.title} accessibilityRole="header">{t('report.ingredients')}</Text>
      <Text style={styles.note}>{t('report.editorialNote')}</Text>
      <SkinConcernRail concerns={concerns} active={active} onChange={onChange} />
      {ingredients.map((id) => <View key={id} style={styles.ingredient}>
        <View style={styles.ingredientHead}><Text style={styles.cardTitle}>{t(`report.ingredient.${id}`)}</Text>
          <Ionicons name="flask-outline" size={22} color={theme.colors.accent} /></View>
        <Text style={styles.body}>{t('report.ingredientBody', { concern: t(`concern.${active}` as TranslationKey) })}</Text>
        <Text style={styles.pill}>{t(`concern.${active}.body` as TranslationKey)}</Text>
      </View>)}
    </View>
    <View style={styles.routine}>
      <Text style={styles.eyebrow}>{t('report.routine')}</Text>
      <Text style={styles.title}>{t('report.goal')}</Text>
      <Text style={styles.body}>{t('report.routineBody')}</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.rail}>
        {(['morning', 'evening', 'extra'] as const).map((step, i) => <View key={step} style={styles.step}>
          <View style={styles.stepHead}><Text style={styles.number}>{String(i + 1).padStart(2, '0')}</Text>
            <Ionicons name={step === 'morning' ? 'sunny-outline' : step === 'evening' ? 'moon-outline' : 'sparkles-outline'} size={24} color={theme.colors.accent} /></View>
          <Text style={styles.pill}>{t(`report.${step}`)}</Text>
          <Text style={styles.cardTitle}>{t(`report.${step}Title`)}</Text>
          <Text style={styles.body}>{t(`report.${step}Body`)}</Text>
        </View>)}
      </ScrollView>
    </View>
    <View style={styles.section}>
      <Text style={styles.title} accessibilityRole="header">{t('report.tips')}</Text>
      <View style={styles.tips}>
        <View style={styles.tip}><Ionicons name="heart-outline" size={24} color={theme.colors.accent} /><View style={styles.tipCopy}>
          <Text style={styles.cardTitle}>{t('report.tipTitle')}</Text><Text style={styles.body}>{t('report.tipBody')}</Text>
        </View></View>
        <View style={[styles.tip, styles.tipBorder]}><Ionicons name="journal-outline" size={24} color={theme.colors.accent} /><View style={styles.tipCopy}>
          <Text style={styles.cardTitle}>{t('report.tipSecondTitle')}</Text><Text style={styles.body}>{t('report.tipSecondBody')}</Text>
        </View></View>
      </View>
    </View>
  </View>;
}

const styles = StyleSheet.create({
  section: { padding: 24, gap: 16 }, title: { color: theme.colors.ink, fontSize: 21, lineHeight: 30, fontWeight: '800' },
  note: { fontSize: 11, color: theme.colors.inkMuted, lineHeight: 18 }, body: { fontSize: 14, lineHeight: 23, color: theme.colors.inkMuted },
  cardTitle: { fontSize: 17, lineHeight: 25, fontWeight: '700', color: theme.colors.ink },
  ingredient: { padding: 18, borderRadius: 14, borderWidth: 1, borderColor: theme.colors.border, backgroundColor: theme.colors.card, gap: 12 },
  ingredientHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
  pill: { alignSelf: 'flex-start', color: theme.colors.rose, backgroundColor: theme.colors.roseSoft, paddingHorizontal: 10, paddingVertical: 5, borderRadius: 6, fontSize: 11, fontWeight: '700' },
  routine: { padding: 24, gap: 14, backgroundColor: theme.colors.roseSoft }, eyebrow: { fontSize: 11, letterSpacing: 1, fontWeight: '700', color: theme.colors.rose },
  rail: { gap: 12, paddingVertical: 8 }, step: { width: 252, backgroundColor: theme.colors.card, padding: 20, borderRadius: 16, gap: 14 },
  stepHead: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }, number: { fontFamily: theme.fontFamily.display, fontSize: 34, color: theme.colors.rose },
  tips: { padding: 18, backgroundColor: theme.colors.chip, borderRadius: 16 }, tip: { flexDirection: 'row', alignItems: 'flex-start', gap: 14, paddingVertical: 10 },
  tipCopy: { flex: 1, gap: 10 }, tipBorder: { borderTopWidth: 1, borderTopColor: theme.colors.border, marginTop: 12, paddingTop: 22 },
});
