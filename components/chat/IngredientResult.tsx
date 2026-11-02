import Ionicons from '@expo/vector-icons/Ionicons';
import { StyleSheet, Text, View } from 'react-native';
import { theme } from '@/constants/theme';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import type { ChatIngredientResult, ChatProductRef } from '@/types';

export type IngredientResultProps = {
  heading: string;
  summary: string;
  notice: string;
  product?: {
    name: string;
    brand?: string;
    source?: string;
    ingredients?: { name: string; description: string }[];
    ingredientNote?: string;
    checks?: { label: string; status: string }[];
  };
  labels: { product: string; ingredients: string; source: string; unknown?: string };
  results?: ChatIngredientResult[];
  products?: ChatProductRef[];
  shadeSelections?: Record<string, string>;
};

const reasons: Record<string, string> = {
  shade_required: 'selection', mapping_not_verified: 'mapping', mapping_not_available: 'mapping',
  evidence_not_reviewed: 'review', absence_not_verifiable: 'partial',
  catalog_version_mismatch: 'version', source_version_mismatch: 'version',
  source_version_unverified: 'version', product_not_found: 'productMissing',
  shade_not_found: 'shadeMissing', source_unavailable: 'server',
  timeout: 'network', network_error: 'network', invalid_response: 'invalid',
  http_error: 'server', ingredient_present: 'present',
  ingredient_absent_from_verified_list: 'absent', verified_evidence: 'verified',
  evidence_requires_review: 'review', ingredients_raw_unavailable: 'unknown', synthetic_test_only: 'review',
};

export function IngredientResult({ heading, summary, notice, product, labels, results, products, shadeSelections }: IngredientResultProps) {
  const { t } = useI18n();
  return (
    <View style={styles.result}>
      <View style={styles.answer}>
        <View style={styles.answerHeader}>
          <View style={styles.answerIcon}>
            <Ionicons name="flask-outline" size={14} color={theme.colors.rose} />
          </View>
          <Text style={styles.answerTitle}>{heading}</Text>
        </View>
        <Text style={styles.summary}>{summary}</Text>
      </View>
      {results?.map((result, index) => {
        const target = products?.find((item) => item.id === result.productId);
        if (!target || (result.shadeId && shadeSelections && shadeSelections[result.productId] !== result.shadeId)) return null;
        const syntheticBlocked = !__DEV__ && !!result.synthetic;
        const verified = !syntheticBlocked && result.status === 'ok' && result.mappingStatus === 'reproduced' &&
          result.reviewStatus === 'verified' && result.ingredientCoverage !== 'unknown' &&
          !!result.shadeId && !!result.optionId && !!result.source && !!result.evidenceId &&
          !!result.collectedAt && !!result.sourceVersion && !!result.sourceFingerprint &&
          !!result.generatorVersion && !!result.ingredients?.length && !result.issues?.length;
        const checks = (result.conditions ?? []).filter((check) => check.productId === result.productId &&
          check.shadeId === result.shadeId && check.optionId === result.optionId);
        const complete = verified && result.ingredientCoverage === 'full' &&
          result.normalizationStatus === 'verified' && result.ingredients.every((item, i) => item.sequence === i + 1);
        const absenceUnverified = !complete && checks.some((check) =>
          (check.operator === 'excludes' && check.verdict === 'MATCH') ||
          (check.operator === 'includes' && check.verdict === 'NOT_MATCH'));
        const verdict = result.verdict === 'ERROR' || result.status === 'error' ? 'ERROR'
          : verified && !absenceUnverified ? result.verdict : 'UNKNOWN';
        return <View key={`${result.productId}-${result.shadeId}-${index}`} style={styles.panel}>
          <Text style={styles.productName}>{target.brand} {target.name}</Text>
          <Text style={styles.secondary}>{t('chat.ingredient.shade')}: {result.shadeId ?? t('chat.ingredient.selection')}</Text>
          <Text accessibilityRole="text" style={styles.label}>{t(`chat.ingredient.${verdict}`)}</Text>
          {checks.map((check, i) => (
            <Text key={i} style={styles.secondary}>
              {check.ingredientName} · {t(`chat.ingredient.${check.operator}`)} · {t(`chat.ingredient.${verdict === 'ERROR' ? 'ERROR' : verified && !absenceUnverified ? check.verdict : 'UNKNOWN'}`)}
            </Text>
          ))}
          <Text style={styles.secondary}>{t('chat.ingredient.coverage')}: {t(`chat.ingredient.${result.ingredientCoverage}`)}</Text>
          <Text style={styles.secondary}>{t('chat.ingredient.mappingLabel')}: {t(`chat.ingredient.${result.mappingStatus}`)}</Text>
          <Text style={styles.secondary}>{t('chat.ingredient.reviewLabel')}: {t(`chat.ingredient.${syntheticBlocked ? 'unreviewed' : result.reviewStatus}`)}</Text>
          <Text style={styles.secondary}>{t(`chat.ingredient.${reasons[result.reason] ?? 'unknown'}` as TranslationKey)}</Text>
          {verified ? <>
            <Text selectable style={styles.secondary}>{labels.source}: {result.source}</Text>
            <Text selectable style={styles.secondary}>{t('chat.ingredient.evidence')}: {result.evidenceId}</Text>
            <Text style={styles.secondary}>{result.collectedAt}</Text>
            <Text style={styles.label}>{labels.ingredients}</Text>
            {result.ingredients.map((item, i) => <Text key={i} style={styles.secondary}>{item.sequence ?? '–'}. {item.name}</Text>)}
          </> : null}
          {result.synthetic ? <Text style={styles.secondary}>{t('chat.ingredient.synthetic')}</Text> : null}
        </View>;
      })}
      {product ? (
        <View style={styles.panel}>
          <Text style={styles.label}>{labels.product}</Text>
          {product.brand ? <Text style={styles.secondary}>{product.brand}</Text> : null}
          <Text style={styles.productName}>{product.name}</Text>
          {product.source || labels.unknown ? <Text style={styles.secondary}>{labels.source}: {product.source || labels.unknown}</Text> : null}
        </View>
      ) : null}
      {product?.ingredients?.length ? (
        <View style={styles.panel}>
          <Text style={styles.label}>{labels.ingredients}</Text>
          {product.ingredients.map((ingredient, index) => (
            <View key={`${ingredient.name}-${index}`} style={styles.ingredient}>
              <View style={styles.ingredientIcon}>
                <Ionicons name="leaf-outline" size={18} color={theme.colors.success} />
              </View>
              <View style={styles.ingredientText}>
                <Text style={styles.ingredientName}>{ingredient.name}</Text>
                <Text style={styles.secondary}>{ingredient.description}</Text>
              </View>
            </View>
          ))}
          {product.ingredientNote ? <Text style={styles.secondary}>{product.ingredientNote}</Text> : null}
        </View>
      ) : null}
      {product?.checks?.length ? (
        <View style={styles.checks}>
          {product.checks.map((check, index) => (
            <View key={`${check.label}-${index}`} style={styles.checkRow}>
              <Text style={styles.checkLabel}>{check.label}</Text>
              <Text style={styles.checkStatus}>{check.status}</Text>
            </View>
          ))}
        </View>
      ) : null}
      <View style={styles.notice}>
        <Ionicons name="information-circle-outline" size={19} color={theme.colors.rose} />
        <Text style={styles.noticeText}>{notice}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  result: { gap: 10 },
  answer: { alignSelf: 'flex-start', maxWidth: '94%', backgroundColor: theme.colors.card, borderColor: theme.colors.border, borderWidth: 1, borderRadius: theme.radius.md, paddingHorizontal: 14, paddingVertical: 12, gap: 8 },
  answerHeader: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  answerIcon: { width: 26, height: 26, borderRadius: 13, alignItems: 'center', justifyContent: 'center', backgroundColor: theme.colors.roseSoft },
  answerTitle: { color: theme.colors.roseDark, fontSize: theme.font.caption, fontWeight: '700' },
  summary: { color: theme.colors.ink, fontSize: theme.font.body, lineHeight: 23 },
  panel: { backgroundColor: theme.colors.card, borderColor: theme.colors.border, borderWidth: 1, borderRadius: theme.radius.md, padding: 12, gap: 5 },
  label: { color: theme.colors.ink, fontSize: theme.font.small, fontWeight: '700', lineHeight: 19 },
  productName: { color: theme.colors.ink, fontSize: theme.font.body, fontWeight: '700', lineHeight: 22 },
  secondary: { color: theme.colors.inkMuted, fontSize: theme.font.caption, lineHeight: 19 },
  ingredient: { flexDirection: 'row', alignItems: 'flex-start', gap: 10, paddingTop: 8 },
  ingredientIcon: { width: 32, height: 32, alignItems: 'center', justifyContent: 'center', backgroundColor: theme.colors.roseSoft, borderRadius: theme.radius.pill },
  ingredientText: { flex: 1, gap: 3 },
  ingredientName: { color: theme.colors.ink, fontSize: theme.font.small, fontWeight: '700', lineHeight: 19 },
  checks: { backgroundColor: theme.colors.roseSoft, borderRadius: theme.radius.md, padding: 12, gap: 6 },
  checkRow: { flexDirection: 'row', justifyContent: 'space-between', gap: 8 },
  checkLabel: { flex: 1, color: theme.colors.ink, fontSize: theme.font.small, lineHeight: 20 },
  checkStatus: { flexShrink: 1, color: theme.colors.warning, fontSize: theme.font.small, fontWeight: '700', textAlign: 'right', lineHeight: 20 },
  notice: { flexDirection: 'row', alignItems: 'flex-start', gap: 8, backgroundColor: theme.colors.cream, borderRadius: theme.radius.md, paddingHorizontal: 14, paddingVertical: 12 },
  noticeText: { flex: 1, color: theme.colors.inkMuted, fontSize: theme.font.caption, lineHeight: 19 },
});
