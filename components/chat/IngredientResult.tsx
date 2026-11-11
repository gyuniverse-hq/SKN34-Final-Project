import Ionicons from '@expo/vector-icons/Ionicons';
import { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { theme } from '@/constants/theme';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import type { ChatIngredientResult, ChatProductRef, IngredientVerdict } from '@/types';

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
  ingredient_absent: 'absent', ingredient_absent_from_verified_list: 'absent',
  verified_evidence: 'verified',
  evidence_requires_review: 'review', ingredients_raw_unavailable: 'unknown', synthetic_test_only: 'review',
};

/** Only expose checked ingredient data when the existing server evidence contract permits it. */
function IngredientEvidenceCard({ result, target, labels, selectedShade }: {
  result: ChatIngredientResult;
  target: ChatProductRef;
  labels: IngredientResultProps['labels'];
  selectedShade?: string;
}) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(false);
  const syntheticBlocked = !__DEV__ && !!result.synthetic;
  const direct = result.mappingStatus === 'directly_reviewed';
  const provenance = direct
    ? !!result.reviewedAt && !!result.reviewRef?.trim()
    : result.mappingStatus === 'reproduced' && !!result.collectedAt &&
      !!result.sourceFingerprint && !!result.generatorVersion;
  const blockingIssue = result.issues?.some((issue) => !direct || issue !== 'source_timezone_unknown');
  const shadeValid = result.shadeId === null ? !selectedShade : !!result.shadeId;
  const evidenceVerified = !syntheticBlocked && provenance &&
    result.reviewStatus === 'verified' && result.ingredientCoverage !== 'unknown' &&
    shadeValid && !!result.optionId && !!result.source && !!result.evidenceId &&
    !!result.sourceVersion && !!result.ingredients?.length && !blockingIssue;
  const verified = result.status === 'ok' && evidenceVerified;
  const checks = (result.conditions ?? []).filter((check) => {
    if (check.productId !== result.productId || check.shadeId !== result.shadeId) return false;
    if (check.optionId === null) {
      return (check.verdict === 'ERROR' || check.verdict === 'UNKNOWN') && !check.evidenceId;
    }
    return !!result.optionId && check.optionId === result.optionId;
  });
  const complete = evidenceVerified && result.ingredientCoverage === 'full' &&
    result.normalizationStatus === 'verified' && result.ingredients.every((item, i) => item.sequence === i + 1);
  const absenceUnverified = !complete && checks.some((check) =>
    (check.operator === 'excludes' && check.verdict === 'MATCH') ||
    (check.operator === 'includes' && check.verdict === 'NOT_MATCH'));
  const verdict: IngredientVerdict = result.verdict === 'ERROR' || result.status === 'error' ? 'ERROR'
    : verified && !absenceUnverified ? result.verdict : 'UNKNOWN';
  const verdictStyle = verdict === 'MATCH' ? styles.positive : verdict === 'UNKNOWN'
    ? styles.uncertain : styles.negative;

  return (
    <View style={styles.verdictCard}>
      <View style={styles.verdictHeader}>
        <View style={styles.identity}>
          <Text style={styles.caption}>{t('chat.ingredient.resultFor')}</Text>
          <Text style={styles.productName}>{target.brand} {target.name}</Text>
          {(!verified || result.shadeId !== null) && (
            <Text style={styles.secondary}>{t('chat.ingredient.shade')}: {result.shadeId ?? t('chat.ingredient.selection')}</Text>
          )}
        </View>
        <View style={[styles.verdictIcon, verdictStyle]}>
          <Ionicons name={verdict === 'MATCH' ? 'checkmark-circle-outline' :
            verdict === 'NOT_MATCH' ? 'close-circle-outline' :
              verdict === 'ERROR' ? 'alert-circle-outline' : 'help-circle-outline'}
          size={22} color={verdict === 'MATCH' ? theme.colors.success :
            verdict === 'UNKNOWN' ? theme.colors.warning : theme.colors.danger} />
        </View>
      </View>
      <Text accessibilityRole="text" style={styles.verdictTitle}>{t(`chat.ingredient.${verdict}`)}</Text>
      {checks.length ? <View style={styles.checkGroup}>
        {checks.map((check, i) => {
          const absence = (check.operator === 'excludes' && check.verdict === 'MATCH') ||
            (check.operator === 'includes' && check.verdict === 'NOT_MATCH');
          const verifiedCondition = evidenceVerified && check.optionId === result.optionId &&
            !!check.evidenceId && check.evidenceId === result.evidenceId && (!absence || complete);
          const conditionVerdict = check.verdict === 'ERROR' || check.verdict === 'UNKNOWN'
            ? check.verdict : verifiedCondition ? check.verdict : 'UNKNOWN';
          const detail = conditionVerdict === 'ERROR' || conditionVerdict === 'UNKNOWN'
            ? t(`chat.ingredient.${reasons[check.reason] ?? 'unknown'}` as TranslationKey) : null;
          return (
            <View key={i} style={styles.checkLine}>
              <Text style={styles.checkName}>{check.ingredientName} · {t(`chat.ingredient.${check.operator}`)}</Text>
              <Text style={styles.checkVerdict}>{t(`chat.ingredient.${conditionVerdict}`)}{detail ? ` · ${detail}` : ''}</Text>
            </View>
          );
        })}
      </View> : null}
      <Text style={styles.reason}>{t(`chat.ingredient.${reasons[result.reason] ?? 'unknown'}` as TranslationKey)}</Text>
      <View style={styles.coverageLine}>
        <Text style={styles.coverageText}>{t('chat.ingredient.coverage')}: {t(`chat.ingredient.${result.ingredientCoverage}`)}</Text>
        <Text style={styles.coverageText}>{t('chat.ingredient.reviewLabel')}: {t(`chat.ingredient.${syntheticBlocked ? 'unreviewed' : result.reviewStatus}`)}</Text>
      </View>
      <Pressable accessibilityRole="button"
        accessibilityLabel={t(expanded ? 'chat.ingredient.hideDetails' : 'chat.ingredient.showDetails')}
        accessibilityState={{ expanded }}
        onPress={() => setExpanded((current) => !current)}
        style={styles.detailsToggle}>
        <Text style={styles.detailsToggleText}>{t(expanded ? 'chat.ingredient.hideDetails' : 'chat.ingredient.showDetails')}</Text>
        <Ionicons name={expanded ? 'chevron-up' : 'chevron-down'} color={theme.colors.rose} size={18} />
      </Pressable>
      {expanded ? <View style={styles.details}>
        <Text style={styles.secondary}>{t('chat.ingredient.mappingLabel')}: {t(`chat.ingredient.${result.mappingStatus}`)}</Text>
        {verified ? <>
          <Text selectable style={styles.secondary}>{labels.source}: {result.source}</Text>
          <Text selectable style={styles.secondary}>{t('chat.ingredient.evidence')}: {result.evidenceId}</Text>
          <Text style={styles.secondary}>{result.collectedAt ?? result.collectedAtRaw}</Text>
          <Text style={styles.label}>{labels.ingredients}</Text>
          {result.ingredients.map((item, i) => (
            <Text key={i} style={styles.secondary}>{item.sequence ?? '–'}. {item.name}</Text>
          ))}
        </> : <Text style={styles.secondary}>{t('chat.ingredient.noVerifiedList')}</Text>}
      </View> : null}
      {result.synthetic ? <Text style={styles.synthetic}>{t('chat.ingredient.synthetic')}</Text> : null}
    </View>
  );
}

export function IngredientResult({ heading, summary, notice, product, labels, results, products, shadeSelections }: IngredientResultProps) {
  return (
    <View style={styles.result}>
      <View style={styles.answer}>
        <View style={styles.answerHeader}>
          <View style={styles.answerIcon}><Ionicons name="flask-outline" size={15} color={theme.colors.rose} /></View>
          <Text style={styles.answerTitle}>{heading}</Text>
        </View>
        <Text style={styles.summary}>{summary}</Text>
      </View>
      {results?.map((result, index) => {
        const target = products?.find((item) => item.id === result.productId);
        if (!target || (result.shadeId && shadeSelections && shadeSelections[result.productId] !== result.shadeId)) return null;
        return <IngredientEvidenceCard key={`${result.productId}-${result.shadeId}-${index}`}
          target={target} result={result} labels={labels} selectedShade={shadeSelections?.[result.productId]} />;
      })}
      {product ? <View style={styles.panel}>
        <Text style={styles.label}>{labels.product}</Text>
        {product.brand ? <Text style={styles.secondary}>{product.brand}</Text> : null}
        <Text style={styles.productName}>{product.name}</Text>
        {product.source || labels.unknown ? <Text style={styles.secondary}>{labels.source}: {product.source || labels.unknown}</Text> : null}
      </View> : null}
      {product?.ingredients?.length ? <View style={styles.panel}>
        <Text style={styles.label}>{labels.ingredients}</Text>
        {product.ingredients.map((ingredient, index) => (
          <View key={`${ingredient.name}-${index}`} style={styles.ingredient}>
            <View style={styles.ingredientIcon}><Ionicons name="leaf-outline" size={18} color={theme.colors.success} /></View>
            <View style={styles.ingredientText}>
              <Text style={styles.ingredientName}>{ingredient.name}</Text>
              <Text style={styles.secondary}>{ingredient.description}</Text>
            </View>
          </View>
        ))}
        {product.ingredientNote ? <Text style={styles.secondary}>{product.ingredientNote}</Text> : null}
      </View> : null}
      {product?.checks?.length ? <View style={styles.checks}>
        {product.checks.map((check, index) => (
          <View key={`${check.label}-${index}`} style={styles.checkRow}>
            <Text style={styles.checkLabel}>{check.label}</Text>
            <Text style={styles.checkStatus}>{check.status}</Text>
          </View>
        ))}
      </View> : null}
      <View style={styles.notice}>
        <Ionicons name="information-circle-outline" size={19} color={theme.colors.rose} />
        <Text style={styles.noticeText}>{notice}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  result: { gap: 12 },
  answer: { alignSelf: 'flex-start', maxWidth: '94%', backgroundColor: theme.colors.card,
    borderColor: theme.colors.border, borderWidth: 1, borderRadius: theme.radius.lg, padding: 14, gap: 8 },
  answerHeader: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  answerIcon: { width: 28, height: 28, borderRadius: 14, alignItems: 'center', justifyContent: 'center', backgroundColor: theme.colors.roseSoft },
  answerTitle: { color: theme.colors.roseDark, fontSize: theme.font.caption, fontWeight: '700' },
  summary: { color: theme.colors.ink, fontSize: theme.font.body, lineHeight: 23 },
  verdictCard: { gap: 10, padding: 16, borderWidth: 1, borderColor: theme.colors.border, borderRadius: theme.radius.lg, backgroundColor: theme.colors.card },
  verdictHeader: { flexDirection: 'row', gap: 12, alignItems: 'center' },
  identity: { flex: 1, gap: 3 },
  caption: { color: theme.colors.rose, fontSize: theme.font.caption, fontWeight: '700' },
  productName: { color: theme.colors.ink, fontSize: theme.font.body, fontWeight: '700', lineHeight: 22 },
  verdictIcon: { width: 44, height: 44, borderRadius: 22, alignItems: 'center', justifyContent: 'center' },
  positive: { backgroundColor: '#E8F3EC' },
  negative: { backgroundColor: '#FDEDEB' },
  uncertain: { backgroundColor: theme.colors.warningBg },
  verdictTitle: { color: theme.colors.ink, fontSize: theme.font.body, fontWeight: '700', lineHeight: 23 },
  checkGroup: { gap: 8, backgroundColor: theme.colors.surface, borderRadius: theme.radius.md, padding: 12 },
  checkLine: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, justifyContent: 'space-between' },
  checkName: { color: theme.colors.ink, fontSize: theme.font.small, flexShrink: 1 },
  checkVerdict: { color: theme.colors.roseDark, fontSize: theme.font.caption, fontWeight: '700', flexShrink: 1 },
  reason: { color: theme.colors.inkMuted, fontSize: theme.font.small, lineHeight: 20 },
  coverageLine: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  coverageText: { color: theme.colors.inkMuted, fontSize: theme.font.caption, lineHeight: 18 },
  detailsToggle: { minHeight: theme.hitTarget, paddingHorizontal: 14, flexDirection: 'row', alignItems: 'center',
    justifyContent: 'space-between', borderWidth: 1, borderRadius: theme.radius.md, borderColor: theme.colors.border,
    backgroundColor: theme.colors.surface },
  detailsToggleText: { color: theme.colors.roseDark, fontSize: theme.font.small, fontWeight: '700' },
  details: { gap: 6, padding: 12, backgroundColor: theme.colors.cream, borderRadius: theme.radius.md },
  secondary: { color: theme.colors.inkMuted, fontSize: theme.font.caption, lineHeight: 19 },
  label: { color: theme.colors.ink, fontSize: theme.font.small, fontWeight: '700', lineHeight: 19 },
  synthetic: { color: theme.colors.warning, fontSize: theme.font.caption, lineHeight: 18 },
  panel: { backgroundColor: theme.colors.card, borderColor: theme.colors.border, borderWidth: 1, borderRadius: theme.radius.lg, padding: 14, gap: 6 },
  ingredient: { flexDirection: 'row', alignItems: 'flex-start', gap: 10, paddingTop: 8 },
  ingredientIcon: { width: 32, height: 32, borderRadius: theme.radius.pill, backgroundColor: theme.colors.roseSoft, alignItems: 'center', justifyContent: 'center' },
  ingredientText: { flex: 1, gap: 3 },
  ingredientName: { color: theme.colors.ink, fontSize: theme.font.small, fontWeight: '700' },
  checks: { gap: 6, padding: 12, backgroundColor: theme.colors.roseSoft, borderRadius: theme.radius.md },
  checkRow: { flexDirection: 'row', gap: 8, justifyContent: 'space-between' },
  checkLabel: { flex: 1, color: theme.colors.ink, fontSize: theme.font.small },
  checkStatus: { flexShrink: 1, color: theme.colors.warning, fontSize: theme.font.small, fontWeight: '700' },
  notice: { flexDirection: 'row', alignItems: 'flex-start', gap: 8, padding: 12, backgroundColor: theme.colors.cream, borderRadius: theme.radius.md },
  noticeText: { flex: 1, color: theme.colors.inkMuted, fontSize: theme.font.caption, lineHeight: 19 },
});
