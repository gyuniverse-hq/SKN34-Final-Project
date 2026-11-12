import { useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Stack, useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRecommendationComparison } from '@/hooks/useRecommendationComparison';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import { Button } from '@/components/ui/Button';
import { theme } from '@/constants/theme';
import type { ComparisonAge } from '@/types/recommendationComparison';

const AGES: ComparisonAge[] = ['10대', '20대', '30대', '40대', '50대', '60대'];

export default function RecommendationComparisonScreen() {
  const { t } = useI18n();
  const router = useRouter();
  const flow = useRecommendationComparison();
  const [evidence, setEvidence] = useState(false);
  const result = flow.mutation.data;
  if (!__DEV__) return <Text>{t('comparison.disabled')}</Text>;
  return <SafeAreaView style={styles.screen}>
    <Stack.Screen options={{ title: t('comparison.title') }} />
    <ScrollView contentContainerStyle={styles.content}>
      <Text style={styles.heading}>{t('comparison.title')}</Text>
      <Text>{t('comparison.intro')}</Text>
      <Text style={styles.notice}>{t('comparison.limitations')}</Text>
      <Text style={styles.label}>{t('comparison.age')}</Text>
      <View style={styles.choices}>{AGES.map(age => <Pressable key={age} accessibilityRole="radio"
        accessibilityState={{ checked: flow.age === age }} onPress={() => flow.setAge(age)}
        style={[styles.choice, flow.age === age && styles.selected]}>
        <Text>{t('comparison.decade', { age: parseInt(age, 10) })}</Text>
      </Pressable>)}</View>
      <Text style={styles.label}>{t('comparison.gender')}</Text>
      <View style={styles.choices}>{(['남성', '여성'] as const).map(gender => <Pressable key={gender}
        accessibilityRole="radio" accessibilityState={{ checked: flow.gender === gender }}
        onPress={() => flow.setGender(gender)} style={[styles.choice, flow.gender === gender && styles.selected]}>
        <Text>{t(gender === '남성' ? 'comparison.male' : 'comparison.female')}</Text>
      </Pressable>)}</View>
      <Button label={t('comparison.run')} onPress={flow.run} disabled={flow.loading || flow.mutation.isPending} />
      <Button label={t('comparison.analyze')} variant="secondary" onPress={() => router.push('/skin-analysis')} />
      {flow.loading || flow.mutation.isPending ? <ActivityIndicator /> : null}
      {flow.problem ? <Text accessibilityRole="alert">{t(flow.problem as TranslationKey)}</Text> : null}
      {flow.mutation.isError ? <Text accessibilityRole="alert">{t('comparison.unavailable')}</Text> : null}
      {result ? <>
        <Text style={styles.label}>{t('comparison.input')}</Text>
        <Text selectable>{JSON.stringify(result.input, null, 2)}</Text>
        <Text style={styles.heading}>{t(`support.priorityChoice.${result.targetConcern}`)}</Text>
        {!result.sameSnapshot ? <Text style={styles.notice}>{t('comparison.mismatch')}</Text> : null}
        <Text>{t('comparison.overlap', { count: result.overlapProductIds.length })}</Text>
        <View style={styles.columns}>
          <View style={styles.column}>
            <Text style={styles.heading}>{t('comparison.v1')}</Text>
            <Text>{t('comparison.status', { status: result.v1.status })}</Text>
            <Text>{result.v1.strategyVersion}</Text>
            {result.v1.matches.map((item, index) => <View key={item.product.id} style={styles.card}>
              <Text style={styles.label}>{index + 1}. {item.product.nameKo || item.product.name}</Text>
              <Text selectable>{item.optionId}</Text>
              <Text selectable>{result.v1.selectedTrace?.find(r => r.optionId === item.optionId)?.ingredients.join(', ') || t('comparison.unknown')}</Text>
            </View>)}
          </View>
          <View style={styles.column}>
            <Text style={styles.heading}>{t('comparison.v2')}</Text>
            <Text>{t('comparison.status', { status: result.v2.status })}</Text>
            <Text style={styles.label}>{t('comparison.core')}</Text>
            {result.v2.coreIngredients?.map(i => <Text key={i.id}>{i.rank}. {i.name} ({i.id}) · {i.score.toFixed(3)}</Text>)}
            <Text style={styles.label}>{t('comparison.expanded')}</Text>
            <Text>{t('comparison.expansionPreview', { count: result.v2.expandedIngredients?.length ?? 0 })}</Text>
            {result.v2.expandedIngredients?.length ? result.v2.expandedIngredients.slice(0, 20).map(i => <View key={i.id}>
              <Text>{i.name} ({i.id}) · {t(i.source === 'ml_shared_tag' ? 'comparison.sharedSource' : 'comparison.concernSource')}</Text>
              <Text style={styles.small}>{i.concernFunctions.join(', ')}</Text>
              {i.origins.map(o => <Text key={o.seedId} style={styles.small}>{o.seedId} → {o.functions.join(', ')}</Text>)}
            </View>) : <Text>{t('comparison.none')}</Text>}
            <Text>{t('comparison.candidates', { count: result.v2.candidateProducts ?? 0 })}</Text>
            <Text>{t('comparison.excluded', { count: result.v2.excludedProducts ?? 0 })}</Text>
            <Text>{t('comparison.reviewScope')}</Text>
            {!result.v2.reviewAppliedProducts ? <Text style={styles.notice}>{t('comparison.reviewMissing')}</Text> : null}
            <Text style={styles.label}>{t('comparison.products')}</Text>
            {result.v2.matches.map(item => <View key={item.productId} style={styles.card}>
              <Text style={styles.label}>{item.rank}. {item.productName}</Text>
              <Text selectable>{item.optionId}</Text>
              <Text>{t('comparison.direct')}: {item.directIngredientIds.join(', ') || t('comparison.none')}</Text>
              <Text>{t('comparison.related')}: {item.expandedIngredientIds.join(', ') || t('comparison.none')}</Text>
              <Text>{t('comparison.rank', { before: item.rankBeforeReview, after: item.rank })}</Text>
              <Text>{t('comparison.scoreParts', { base: item.ingredientContribution.toFixed(4), review: item.reviewContribution.toFixed(4), diversity: item.diversityPenalty.toFixed(4) })}</Text>
              <Text selectable>{JSON.stringify(item.review)}</Text>
            </View>)}
          </View>
        </View>
        <Button label={t('comparison.evidence')} variant="secondary" onPress={() => setEvidence(!evidence)} />
        {evidence ? <Text selectable style={styles.small}>{JSON.stringify(result, null, 2)}</Text> : null}
      </> : null}
    </ScrollView>
  </SafeAreaView>;
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  content: { padding: 20, gap: 14, maxWidth: 1100, width: '100%', alignSelf: 'center' },
  heading: { fontSize: 21, fontWeight: '700', color: theme.colors.ink },
  label: { fontSize: 15, fontWeight: '600' }, small: { fontSize: 12 },
  choices: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  choice: { padding: 12, borderWidth: 1, borderColor: '#c5c5c5', borderRadius: 10 },
  selected: { backgroundColor: '#fce0e7', borderColor: '#a84965' },
  columns: { flexDirection: 'row', flexWrap: 'wrap', gap: 20 },
  column: { flex: 1, minWidth: 260, gap: 9 },
  card: { padding: 12, gap: 6, backgroundColor: '#f7f3f4', borderRadius: 10 },
  notice: { backgroundColor: '#fff2d5', padding: 12, borderRadius: 10, lineHeight: 21 },
});
