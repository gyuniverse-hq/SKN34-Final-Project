import { useRef, useState, type ComponentRef } from 'react';
import { Image } from 'expo-image';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { ProductImage } from '@/components/ui/ProductImage';
import { ProductCompareSheet } from './ProductCompareSheet';
import { theme } from '@/constants/theme';
import { canTryOn } from '@/lib/catalog';
import type { ChatCondition } from '@/lib/chatConditions';
import { formatKRW } from '@/lib/format';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import { parseCategory, parseId } from '@/lib/routes';
import type { OwnedLookOptionDisplay, CompoundConsultation, ChatOptionSearch, ChatProductEvidence, ChatStyleRecipe, Product } from '@/types';

interface Props {
  optionSearch?: ChatOptionSearch;
  sourceProducts?: ChatStyleRecipe['products'];
  products: Product[];
  loading: boolean;
  failed: boolean;
  missingCount: number;
  conditions: ChatCondition[];
  showIngredients: boolean;
  onRetry: () => void;
  onOpenProduct: (id: string, shadeId?: string, optionId?: string) => void;
  onOpenAr: (productId: string, shadeId: string) => void;
  disabledActions?: boolean;
  previewImage?: number;
  candidateOrder?: string[];
  evidence?: ChatProductEvidence[];
  selectedShades?: Record<string, string>;
  onSelectShade?: (productId: string, shadeId: string) => void;
  /** Explicit selection is independent of swiping between candidates. */
  onSelectProduct?: (productId: string) => void;
  selectedProductId?: string | null;
  /** Product IDs in this response, not all candidates retained from previous turns. */
  expectedIds?: string[];
  fragrance?: 'verified' | 'unknown';
  onOpenEvidence?: (productId: string) => void;
}

function conditionMatch(product: Product, condition: ChatCondition): boolean | undefined {
  if (condition.kind === 'category' && typeof condition.value === 'string') {
    const requestedCategory = parseCategory(condition.value);
    const productCategory = parseCategory(product.category);
    if (!requestedCategory || !productCategory || requestedCategory !== condition.value || productCategory !== product.category) return undefined;
    return productCategory === requestedCategory;
  }
  if (condition.kind === 'maxPrice' && typeof condition.value === 'number' &&
      Number.isFinite(condition.value) && condition.value >= 0 &&
      Number.isFinite(product.priceKRW) && product.priceKRW > 0) {
    return product.priceKRW <= condition.value;
  }
  return undefined;
}

function candidateStatus(product: Product, required: ChatCondition[]): 'matched' | 'unverified' | 'mismatched' {
  const matches = required.map((condition) => conditionMatch(product, condition));
  if (matches.includes(false)) return 'mismatched';
  if (matches.includes(undefined)) return 'unverified';
  return 'matched';
}

function optionShadeLabel(shadeId: string, items: ChatOptionSearch['items']): TranslationKey {
  const groups = new Set(items.filter((item) => item.shadeId === shadeId).map((item) => item.group));
  if (!groups.size) return 'chat.conditionUnknown';
  // A shade can represent multiple source options. Only a unanimous verdict confirms its status.
  if (groups.size !== 1 || groups.has('REFERENCE_ONLY')) return 'chat.option.reference';
  return groups.has('ELIGIBLE') ? 'chat.option.eligible' : 'chat.conditionNotMet';
}

type VerifiedPrice = NonNullable<ChatOptionSearch['items'][number]['price']>;

function CompoundPrice({ price }: { price: VerifiedPrice }) {
  const { t, language } = useI18n();
  const [open, setOpen] = useState(false);
  const day = /^(\d{4}-\d{2}-\d{2})(?:T|\s|$)/.exec(price.observedAt ?? price.observedAtRaw ?? '')?.[1];
  const date = day ? new Date(`${day}T00:00:00Z`) : undefined;
  const verifiedDate = day && date && Number.isFinite(date.getTime()) && date.toISOString().startsWith(day)
    ? date.toLocaleDateString(language, { year: 'numeric', month: 'numeric', day: 'numeric', timeZone: 'UTC' }) : undefined;
  let host: string | undefined;
  if (open && /^https?:\/\//i.test(price.sourceRef)) {
    try { host = new URL(price.sourceRef).hostname; } catch { /* A source reference can be an opaque catalog ID. */ }
  }
  return <View>
    <View style={styles.compoundPriceRow}>
      <Text style={styles.price}>{t('chat.compound.amount', { amount: price.amountKRW.toLocaleString(language) })}</Text>
      <Pressable accessibilityRole="button" aria-expanded={open} accessibilityLabel={t('chat.compound.priceInfo')} onPress={() => setOpen((value) => !value)}
        style={styles.priceToggle}>
        <Text style={styles.link}>{t('chat.compound.priceInfo')}</Text>
      </Pressable>
    </View>
    {open ? <View style={styles.ingredientBlock}>
      <Text style={styles.notice}>{t(price.observedBasis === 'catalog_reference' ? 'chat.compound.catalogPrice' : 'chat.compound.collectedPrice')}</Text>
      {host ? <Text style={styles.notice}>{t('chat.compound.priceSite', { host })}</Text> : null}
      <Text style={styles.notice}>{verifiedDate ? t('chat.compound.priceDay', { day: verifiedDate }) : t('chat.compound.noPriceDay')}</Text>
    </View> : null}
  </View>;
}

/** Use the exact option snapshot the server verified, including options without a shade. */
export function CompoundProductCards({ result, onOpenProduct }: {
  result: CompoundConsultation;
  onOpenProduct: (id: string, shadeId?: string, optionId?: string) => void;
}) {
  const { t } = useI18n();
  const [showScope, setShowScope] = useState(false);
  if (!result.goal.wantsProducts) return null;
  const cards = result.options.flatMap(({ candidate, outcome, verification }) => {
    if (outcome !== 'eligible' || verification?.group !== 'ELIGIBLE' ||
        verification.productId !== candidate.productId || verification.optionId !== candidate.optionId ||
        !verification.checks.length || verification.checks.some((check) => check.verdict !== 'MATCH')) return [];
    return [{ candidate, verification }];
  }).sort((a, b) => a.candidate.rank - b.candidate.rank);
  const excluded = result.options.filter((item) => item.outcome === 'excluded').length;
  const failed = result.options.filter((item) => item.outcome === 'failed').length;
  const scopes = result.batches.flatMap((batch) => batch.scope ? [batch.scope] : []);
  const missingBatches = result.batches.length - scopes.length;
  const timedOut = scopes.some((scope) => scope.stoppedReason === 'TIMEOUT');
  return (
    <View style={styles.list}>
      {cards.map(({ candidate, verification }) => {
        const price = verification.price;
        return <View key={JSON.stringify([candidate.productId, candidate.optionId])} style={styles.card}>
          <Text style={styles.brand}>{candidate.brand}</Text>
          <Text style={styles.name}>{candidate.productName} · {candidate.optionName.trim() || candidate.optionId}</Text>
          {verification.synthetic ? <Text style={styles.notice}>{t('chat.option.synthetic')}</Text> : null}
          {price ? <CompoundPrice price={price} /> : null}
          {verification.checks.flatMap((check, index) => {
            if (check.condition === 'fragrance_free') return <Text key={index} style={styles.conditionLabel}>{t('chat.ingredient.fragranceVerified')}</Text>;
            if (check.condition !== 'ingredient' || !check.ingredientName || !check.operator) return [];
            return <Text key={index} style={styles.conditionLabel}>{t(check.operator === 'excludes'
              ? 'chat.compound.ingredientAbsent' : 'chat.compound.ingredientPresent', { name: check.ingredientName })}</Text>;
          })}
          {parseId(candidate.productId) === candidate.productId ? <Pressable accessibilityRole="button" style={styles.open}
            onPress={() => onOpenProduct(candidate.productId, verification.shadeId ?? undefined, candidate.optionId)}>
            <Text style={styles.link}>{t('styleLooks.openProduct')}</Text>
          </Pressable> : null}
        </View>;
      })}
      {result.options.length || result.batches.length ? <View style={styles.conditionPanel}>
        <Pressable accessibilityRole="button" aria-expanded={showScope}
          onPress={() => setShowScope((open) => !open)} style={styles.retry}>
          <Text style={styles.link}>{t(showScope ? 'chat.option.scopeHide' : 'chat.option.scopeShow')}</Text>
        </Pressable>
        {showScope ? <>
          <Text style={styles.notice}>{t('chat.compound.outcomes', {
            eligible: cards.length, excluded, failed, unknown: result.options.length - cards.length - excluded - failed,
          })}</Text>
          {cards.map(({ candidate }) => <Text key={candidate.rank} style={styles.notice}>{t('chat.compound.rank', { rank: candidate.rank, name: candidate.productName })}</Text>)}
          {scopes.length ? <>
            {!missingBatches ? <Text style={styles.notice}>{t(timedOut ? 'chat.option.scopeTimeout'
              : scopes.every((scope) => scope.exhaustive) ? 'chat.option.scopeComplete' : 'chat.option.scopeLimited')}</Text> : null}
            <Text style={styles.notice}>{t('chat.option.scopeProgress', {
              checked: scopes.reduce((count, scope) => count + scope.checkedOptions, 0),
              total: scopes.reduce((count, scope) => count + scope.candidateOptions, 0),
            })}</Text>
          </> : null}
          {missingBatches ? <Text style={styles.notice}>{t('chat.option.scopeErrors', { count: missingBatches })}</Text> : null}
        </> : null}
      </View> : null}
    </View>
  );
}

/** N02 keeps batch evidence and selects exact sale options, never the product headline price. */
export function OwnedLookOptionCards({ result, onOpenProduct }: {
  result: OwnedLookOptionDisplay;
  onOpenProduct: (id: string, shadeId?: string, optionId?: string) => void;
}) {
  const { t } = useI18n();
  const [showScope, setShowScope] = useState(false);
  const cards = result.selections.flatMap((selection) => {
    const matches = result.batches.filter(batch => batch.status !== 'ERROR' && batch.effectiveRequest?.priceBasis !== 'current_offer').flatMap(batch => batch.items)
      .filter(item => item.productId === selection.productId && (item.shadeId ?? null) === (selection.shadeId ?? null) && item.optionId === selection.optionId);
    // Conflicting or duplicated evidence cannot silently select a different sale option.
    if (matches.length !== 1 || matches[0].group !== 'ELIGIBLE' || !matches[0].checks.length ||
        matches[0].checks.some(check => check.verdict !== 'MATCH')) return [];
    return [{ selection, item: matches[0] }];
  });
  return <View style={styles.list}>
    {cards.map(({ selection, item }) => <View key={JSON.stringify([selection.productId, selection.shadeId, selection.optionId])} style={styles.card}>
      <Text style={styles.brand}>{selection.brand}</Text>
      <Text style={styles.name}>{selection.productName} · {selection.shadeName}</Text>
      {item.synthetic ? <Text style={styles.notice}>{t('chat.option.synthetic')}</Text> : null}
      {item.price ? <CompoundPrice price={item.price} /> : <Text style={styles.notice}>{t('chat.conditionUnknown')}</Text>}
      {item.checks.flatMap((check, index) => {
        if (check.condition === 'fragrance_free') return <Text key={index} style={styles.conditionLabel}>{t('chat.ingredient.fragranceVerified')}</Text>;
        if (check.condition !== 'ingredient' || !check.ingredientName || !check.operator) return [];
        return <Text key={index} style={styles.conditionLabel}>{t(check.operator === 'excludes'
          ? 'chat.compound.ingredientAbsent' : 'chat.compound.ingredientPresent', { name: check.ingredientName })}</Text>;
      })}
      {parseId(selection.productId) === selection.productId && (!selection.shadeId || parseId(selection.shadeId) === selection.shadeId) ?
        <Pressable accessibilityRole="button" style={styles.open} onPress={() => onOpenProduct(selection.productId, selection.shadeId ?? undefined, selection.optionId)}>
          <Text style={styles.link}>{t('styleLooks.openProduct')}</Text>
        </Pressable> : null}
    </View>)}
    <Pressable accessibilityRole="button" aria-expanded={showScope} onPress={() => setShowScope(value => !value)} style={styles.retry}>
      <Text style={styles.link}>{t(showScope ? 'chat.option.scopeHide' : 'chat.option.scopeShow')}</Text>
    </Pressable>
    {showScope ? <View style={styles.conditionPanel}>
      {result.batches.map((batch, index) => <View key={index}>
        <Text style={styles.notice}>{t(batch.checkedScope.stoppedReason === 'TIMEOUT' ? 'chat.option.scopeTimeout'
          : batch.checkedScope.exhaustive ? 'chat.option.scopeComplete' : 'chat.option.scopeLimited')}</Text>
        <Text style={styles.notice}>{t('chat.option.scopeProgress', { checked: batch.checkedScope.checkedOptions, total: batch.checkedScope.candidateOptions })}</Text>
        {batch.checkedScope.errors ? <Text style={styles.notice}>{t('chat.option.scopeErrors', { count: batch.checkedScope.errors })}</Text> : null}
        <Text style={styles.notice}>{batch.checkedAt}</Text>
        {batch.items.flatMap(item => item.checks.filter(check => check.sourceRef).map((check, checkIndex) =>
          <Text key={JSON.stringify([item.productId, item.optionId, checkIndex])} style={styles.notice}>{t('chat.option.evidenceSource', { source: check.sourceRef! })}</Text>))}
      </View>)}
      {result.failedProductIds.length ? <Text style={styles.notice}>{t('chat.option.scopeErrors', { count: result.failedProductIds.length })}</Text> : null}
    </View> : null}
  </View>;
}

export function ChatProducts({ optionSearch, sourceProducts, products, loading, failed, missingCount, conditions, showIngredients, onRetry, onOpenProduct, onOpenAr, disabledActions = false, previewImage, candidateOrder, evidence, selectedShades: controlledShades, onSelectShade, onSelectProduct, selectedProductId, expectedIds, fragrance, onOpenEvidence }: Props) {
  const { t } = useI18n();
  const [selectedShades, setSelectedShades] = useState<Record<string, string>>({});
  const [compareOpen, setCompareOpen] = useState(false);
  const requiredConditions = optionSearch ? [] : conditions.filter((condition) => condition.required);
  const ordered = candidateOrder ? [...products].sort((a, b) => {
    const rank = (id: string) => { const i = candidateOrder.indexOf(id); return i < 0 ? candidateOrder.length : i; };
    return rank(a.id) - rank(b.id);
  }) : products;
  // Server numbering must also be the visual order, even across condition groups.
  const groups = candidateOrder ? ordered.map((product) => ({
    key: product.id, title: requiredConditions.length
      ? `chat.ui.candidates${({ matched: 'Matched', unverified: 'Unverified', mismatched: 'Mismatched' } as const)[candidateStatus(product, requiredConditions)]}` as TranslationKey
      : undefined, products: [product],
  })) : requiredConditions.length ? [
    { key: 'matched', title: 'chat.ui.candidatesMatched' as TranslationKey, products: products.filter((product) => candidateStatus(product, requiredConditions) === 'matched') },
    { key: 'unverified', title: 'chat.ui.candidatesUnverified' as TranslationKey, products: products.filter((product) => candidateStatus(product, requiredConditions) === 'unverified') },
    { key: 'mismatched', title: 'chat.ui.candidatesMismatched' as TranslationKey, products: products.filter((product) => candidateStatus(product, requiredConditions) === 'mismatched') },
  ] : [{ key: 'all', title: undefined, products }];

  // Preserve the original server candidate order/ordinal across condition groups.
  // Each product receives its own slide; swiping never changes selectedProductId.
  const loadedSlides = groups.flatMap((group) => group.products.map((product) => ({
    key: product.id, title: group.title, products: [product],
  })));
  const orderedExpected = expectedIds
    ? [...new Set(expectedIds)].sort((a, b) => {
        const rank = (id: string) => {
          const index = candidateOrder?.indexOf(id) ?? -1;
          return index < 0 ? Number.MAX_SAFE_INTEGER : index;
        };
        return rank(a) - rank(b);
      })
    : undefined;
  const catalogSlides = orderedExpected
    ? orderedExpected.map((id) => loadedSlides.find((slide) => slide.key === id) ?? { key: id, title: undefined, products: [] })
    : loadedSlides;
  const slides: { key: string; title?: TranslationKey; products: Product[]; source?: ChatStyleRecipe['products'][number] }[] = sourceProducts
    ? sourceProducts.map((source, index) => ({ key: `video-${index}`, source,
      products: source.productId ? products.filter((product) => product.id === source.productId) : [] }))
    : catalogSlides;
  const { width: screenWidth } = useWindowDimensions();
  const cardWidth = Math.min(312, Math.max(224, screenWidth - 96));
  const slideStep = cardWidth + 12;
  const carouselRef = useRef<ComponentRef<typeof ScrollView>>(null);
  const [viewedIndex, setViewedIndex] = useState(0);
  const currentIndex = Math.min(viewedIndex, Math.max(0, slides.length - 1));
  const goTo = (index: number) => {
    const next = Math.max(0, Math.min(index, slides.length - 1));
    setViewedIndex(next);
    carouselRef.current?.scrollTo?.({ x: next * slideStep, animated: true });
  };

  return (
    <View style={styles.list}>
      {!optionSearch && conditions.length && products.length ? <Text style={styles.notice}>{t('chat.ui.partialConditionsNotice' as TranslationKey)}</Text> : null}
      {slides.length > 0 ? (
        <View style={styles.carouselHeader}>
          <Text style={styles.carouselCount}>{currentIndex + 1} / {slides.length}</Text>
          <View style={styles.carouselNavigation}>
            <Pressable accessibilityRole="button" accessibilityLabel={t('chat.carousel.previous')}
              disabled={currentIndex === 0} accessibilityState={{ disabled: currentIndex === 0 }}
              onPress={() => goTo(currentIndex - 1)} style={styles.carouselArrow}>
              <Text style={styles.carouselArrowText}>‹</Text>
            </Pressable>
            <Pressable accessibilityRole="button" accessibilityLabel={t('chat.carousel.next')}
              disabled={currentIndex === slides.length - 1} accessibilityState={{ disabled: currentIndex === slides.length - 1 }}
              onPress={() => goTo(currentIndex + 1)} style={styles.carouselArrow}>
              <Text style={styles.carouselArrowText}>›</Text>
            </Pressable>
          </View>
        </View>
      ) : null}
      <ScrollView ref={carouselRef} horizontal
        testID="chat-products-carousel"
        showsHorizontalScrollIndicator={false}
        snapToInterval={slideStep}
        decelerationRate="fast"
        contentContainerStyle={styles.carouselRail}
        onMomentumScrollEnd={({ nativeEvent }) => {
          const index = Math.round(nativeEvent.contentOffset.x / slideStep);
          setViewedIndex(Math.max(0, Math.min(index, slides.length - 1)));
        }}>
      {slides.map((group, slideIndex) => (
        <View key={group.key} style={[styles.group, { width: cardWidth }]}>
          {group.title ? <Text style={styles.groupTitle}>{t(group.title)}</Text> : null}
          {!group.products.length ? <View style={styles.missingCard}>
            <Text style={styles.carouselCount}>{group.source ? t('chat.candidateNumber', { index: slideIndex + 1 }) : candidateOrder?.includes(group.key)
              ? t('chat.candidateNumber', { index: candidateOrder.indexOf(group.key) + 1 })
              : t('chat.conditionUnknown')}</Text>
            {group.source?.label ? <Text style={styles.brand}>{group.source.label}</Text> : null}
            <Text style={styles.notice}>{group.source?.mappingStatus === 'unavailable' ? t('chat.productLoadFailed') : group.source && !group.source.productId ? t('chat.style.mappingNotLinked') : loading ? t('chat.productLoading') : failed
              ? t('chat.productLoadFailed') : t('chat.productMissing', { count: 1 })}</Text>
          </View> : null}
          {group.products.map((product) => {
            const candidateIndex = group.source ? slideIndex : candidateOrder?.indexOf(product.id) ?? -1;
            const proof = evidence?.find((item) => item.productId === product.id);
            const productOptions = optionSearch?.items.filter((item) => item.productId === product.id) ?? [];
            const options = productOptions.filter((item) => item.group !== 'EXCLUDED');
            const validShades = parseId(product.id) === product.id
              ? product.shades.filter((shade) => parseId(shade.id) === shade.id) : [];
            const tryOn = canTryOn(product) && parseId(product.id) === product.id && validShades.length > 0;
            const selectedShade = validShades.find((shade) => shade.id === (controlledShades ?? selectedShades)[product.id]);
            const productCategory = parseCategory(group.source?.zone === 'foundation' && product.id === 'yt-044fc0c5c3441ea932e6' ? 'base' : product.category);
            const priceBasis = optionSearch?.effectiveRequest?.priceBasis ?? options.find((item) => item.price)?.price?.requestedBasis;
            const registeredPrice = optionSearch || proof?.source === 'catalog_api';
            const fragranceUnknown = options.some((item) => item.checks.some((check) =>
              check.condition === 'fragrance_free' && check.verdict === 'UNKNOWN'));
            return (
              <View key={product.id} style={[styles.card, selectedProductId === product.id && styles.cardSelected]}>
                <View style={styles.productHeader}>
                  {disabledActions && previewImage ? <Image source={previewImage} style={styles.image} contentFit="cover" accessible={false} /> :
                    <ProductImage uri={product.imageUrl} category={productCategory} recyclingKey={product.id} style={styles.image} />}
                  <View style={styles.details}>
                    {candidateIndex >= 0 ? <Text style={styles.notice}>{t('chat.candidateNumber', { index: candidateIndex + 1 })}</Text> : null}
                    <Text style={styles.brand}>{product.brand}</Text>
                    <Text style={styles.name}>{product.name}</Text>
                    <Text style={styles.notice}>{productCategory ? t(`shop.cat.${productCategory}` as TranslationKey) : t('chat.conditionUnknown')}</Text>
                    <Text style={styles.price}>{t(registeredPrice ? 'chat.option.registeredPrice' : 'chat.referencePrice')} {Number.isFinite(product.priceKRW) && product.priceKRW > 0 ? formatKRW(product.priceKRW) : t('chat.conditionUnknown')}</Text>
                  </View>
                </View>
                <View style={styles.productBody}>
                  {optionSearch ? <View style={styles.conditionPanel}>
                    <Text style={styles.notice}>{t('chat.option.scopeNotice')}</Text>
                    {fragranceUnknown ? <Text style={styles.notice}>{t('chat.option.fragranceUnknown')}</Text> : null}
                    {options.map((item) => (
                      <View key={item.optionId} style={styles.ingredientBlock}>
                        {item.synthetic ? <Text style={styles.notice}>{t('chat.option.synthetic')}</Text> : null}
                        {item.checks.some((check) => check.reason === 'option_texture_unverified') ? <Text style={styles.notice}>{t('chat.option.textureUnverified')}</Text> : null}
                        {item.ingredientEntryCount != null && item.ingredientIdentityCount != null ? <Text style={styles.notice}>{t('chat.option.identities', { matched: item.ingredientIdentityCount, total: item.ingredientEntryCount })}</Text> : null}
                        {item.checks.filter((check) => check.condition === 'texture').map((check, index) => (
                          <Text key={`texture-${index}`} style={styles.notice}>
                            {t(check.textureBasis === 'official_reviewed' && check.verdict === 'MATCH' ? 'chat.option.textureOfficial'
                              : check.textureBasis === 'product_name' ? 'chat.option.textureName'
                              : check.textureBasis === 'review_ai' || check.textureBasis === 'review_survey' ? 'chat.option.textureReview'
                              : 'chat.option.textureCatalog')}
                          </Text>
                        ))}
                        <Text style={styles.sectionTitle}>{product.shades.find((shade) => shade.id === item.shadeId)?.name ?? t('chat.option.noShade')} · {t(item.group === 'ELIGIBLE' ? 'chat.option.eligible' : 'chat.option.reference')}</Text>
                        {item.checks.filter((check) => check.condition !== 'identity').map((check, index) => {
                          if (check.condition === 'fragrance_free' && check.verdict === 'UNKNOWN') {
                            return null;
                          }
                          if (check.condition === 'price' && priceBasis === 'current_offer' && check.verdict === 'UNKNOWN') {
                            return null;
                          }
                          const label = check.condition === 'ingredient'
                            ? `${check.ingredientName} · ${t(check.operator === 'excludes' ? 'chat.option.excludes' : 'chat.option.includes')}`
                            : t(({ price: 'chat.option.price', texture: 'chat.option.texture', fragrance_free: 'chat.option.fragrance', moisturizing: 'chat.option.moisturizing' } as Record<string, TranslationKey>)[check.condition] ?? 'chat.option.unsupported');
                          return <Text key={index} style={styles.notice}>{label}: {t(check.verdict === 'MATCH' ? 'chat.conditionMet' : check.verdict === 'NOT_MATCH' ? 'chat.conditionNotMet' : check.verdict === 'ERROR' ? 'chat.option.error' : 'chat.conditionUnknown')}{check.condition === 'ingredient' && check.verdict === 'UNKNOWN' ? ` · ${t(check.reason === 'absence_not_verifiable' ? 'chat.ingredient.partial' : check.reason === 'evidence_requires_review' ? 'chat.ingredient.review' : 'chat.ingredient.unknown')}` : ''}</Text>;
                        })}
                        {priceBasis === 'collected_snapshot' && item.price?.observedBasis === 'collected_snapshot' ? <Text style={styles.notice}>{t('chat.option.snapshot')}: {formatKRW(item.price.amountKRW)} · {item.price.observedAt ?? (item.price.observedAtRaw ? `${item.price.observedAtRaw} · ${t('chat.option.timezoneUnknown')}` : t('chat.option.noObservation'))}</Text> : null}
                      </View>
                    ))}
                    {selectedShade && !productOptions.some((item) => item.shadeId === selectedShade.id) ? <Text style={styles.notice}>{t('chat.option.selectionUnverified')}</Text> : null}
                  </View> : null}
                  {fragrance ? <View style={styles.ingredientBlock}>
                    <Text style={styles.notice}>{t(fragrance === 'verified' ? 'chat.ingredient.fragranceVerified' : 'chat.ingredient.fragranceUnknown')}</Text>
                    {fragrance === 'verified' && selectedShade ? <Text style={styles.notice}>{selectedShade.name}</Text> : null}
                    {onOpenEvidence ? <Pressable accessibilityRole="button" onPress={() => onOpenEvidence(product.id)} style={styles.open}>
                      <Text style={styles.notice}>{t('chat.ingredient.showDetails')}</Text>
                    </Pressable> : null}
                  </View> : null}
                  {!optionSearch && !fragrance && proof ? <View style={styles.ingredientBlock}>
                    <Text style={styles.notice}>{t('chat.catalogEvidence')}</Text>
                    <Text style={styles.notice}>{t(proof.ingredientCoverage === 'key_only'
                      ? 'chat.keyOnlyEvidence' : 'chat.noIngredientEvidence')}</Text>
                  </View> : null}
                  {!optionSearch && !fragrance && showIngredients ? (
                    <View style={styles.ingredientBlock}>
                      {product.keyIngredients.length > 0 ? (
                        <>
                          <Text style={styles.notice}>{t('product.keyIngredients')}: {product.keyIngredients.join(', ')}</Text>
                          <Text style={styles.notice}>{t('chat.ui.keyIngredientsNotice')}</Text>
                        </>
                      ) : <Text style={styles.notice}>{t('chat.ui.ingredientUnavailable')}</Text>}
                    </View>
                  ) : null}
                  {!optionSearch && !fragrance && conditions.length ? (
                    <View style={styles.conditionPanel}>
                      <Text style={styles.sectionTitle}>{t('chat.ui.checkConditions')}</Text>
                      {conditions.map((condition, index) => {
                        const matches = conditionMatch(product, condition);
                        const label = `${condition.text}${condition.required ? '' : ` (${t('chat.ui.preferred')})`}`;
                        const status = t(matches === undefined ? 'chat.conditionUnknown' : matches ? 'chat.conditionMet' : 'chat.conditionNotMet');
                        const priceBasis = condition.kind === 'maxPrice' ? t('chat.conditionPriceBasis') : undefined;
                        return (
                          <View key={`${condition.kind}-${index}`} accessible
                            accessibilityLabel={`${label} · ${status}${priceBasis ? ` (${priceBasis})` : ''}`}
                            style={styles.conditionRow}>
                            <View style={styles.conditionDetail}>
                              <Text style={styles.conditionLabel}>
                                {label}{priceBasis ? <Text style={styles.conditionBasis}> · {priceBasis}</Text> : null}
                              </Text>
                            </View>
                            <Text style={[styles.conditionStatus, matches === undefined ? styles.conditionUnknown : matches ? styles.conditionMet : styles.conditionNotMet]}>{status}</Text>
                          </View>
                        );
                      })}
                    </View>
                  ) : null}
                  {fragrance !== 'verified' && validShades.length > 0 ? (
                    <>
                      <Text style={styles.notice}>{t('chat.selectShade')}</Text>
                      <ScrollView horizontal showsHorizontalScrollIndicator contentContainerStyle={styles.shades}>
                        {validShades.map((shade) => {
                          const status = optionSearch ? t(optionShadeLabel(shade.id, productOptions)) : undefined;
                          const label = [product.name, shade.name, status].filter(Boolean).join(', ');
                          return (
                            <Pressable
                              key={shade.id}
                              accessibilityRole="button"
                              accessibilityLabel={label}
                              accessibilityState={{ selected: shade.id === selectedShade?.id, disabled: disabledActions }}
                              disabled={disabledActions}
                              onPress={() => {
                                if (disabledActions) return;
                                setSelectedShades((current) => ({ ...current, [product.id]: shade.id }));
                                onSelectShade?.(product.id, shade.id);
                              }}
                              style={[styles.shade, shade.id === selectedShade?.id && styles.shadeSelected]}>
                              <View style={[styles.swatch, { backgroundColor: shade.hex }]} />
                              <View>
                                <Text style={styles.shadeText}>{shade.name}</Text>
                                {status ? <Text style={styles.notice}>{status}</Text> : null}
                              </View>
                            </Pressable>
                          );
                        })}
                      </ScrollView>
                      {tryOn && !selectedShade ? <Text style={styles.notice}>{t('chat.tryOnAtDetail')}</Text> : null}
                    </>
                  ) : null}
                  {onSelectProduct ? <Pressable
                    accessibilityRole="button"
                    accessibilityLabel={`${t('chat.carousel.choose')}: ${product.name}`}
                    accessibilityState={{ selected: selectedProductId === product.id, disabled: disabledActions }}
                    disabled={disabledActions}
                    onPress={disabledActions ? undefined : () => onSelectProduct(product.id)}
                    style={[styles.selectProduct, selectedProductId === product.id && styles.selectProductActive, disabledActions && styles.disabled]}>
                    <Text style={[styles.selectProductText, selectedProductId === product.id && styles.selectProductTextActive]}>
                      {t(selectedProductId === product.id ? 'chat.carousel.chosen' : 'chat.carousel.choose')}
                    </Text>
                  </Pressable> : null}
                  <View style={styles.actions}>
                    {parseId(product.id) === product.id ? <Pressable
                      accessibilityRole="button"
                      accessibilityLabel={`${product.brand} ${product.name}, ${t('chat.openProduct')}`}
                      accessibilityState={{ disabled: disabledActions }}
                      disabled={disabledActions}
                      onPress={disabledActions ? undefined : () => group.source?.productId === product.id && group.source.optionId ? onOpenProduct(product.id, selectedShade?.id, group.source.optionId) : onOpenProduct(product.id, selectedShade?.id)}
                      style={({ pressed }) => [styles.open, pressed && styles.pressed, disabledActions && styles.disabled]}>
                      <Text style={styles.link}>{t('chat.openProduct')} ›</Text>
                    </Pressable> : null}
                    {tryOn && (selectedShade || disabledActions) ? <Pressable
                      accessibilityRole="button"
                      accessibilityLabel={t('chat.trySelectedShade')}
                      accessibilityState={{ disabled: disabledActions }}
                      disabled={disabledActions}
                      onPress={disabledActions || !selectedShade ? undefined : () => onOpenAr(product.id, selectedShade.id)}
                      style={({ pressed }) => [styles.arButton, pressed && styles.pressed, disabledActions && styles.disabled]}>
                      <Text style={styles.arButtonText}>{t('chat.trySelectedShade')}</Text>
                    </Pressable> : null}
                  </View>
                </View>
              </View>
            );
          })}
        </View>
      ))}
      </ScrollView>
      {ordered.length >= 2 ? <Pressable accessibilityRole="button"
        accessibilityLabel={t('chat.compare.open')}
        onPress={() => setCompareOpen(true)} style={styles.compareOpen}>
        <Text style={styles.compareOpenText}>{t('chat.compare.open')}</Text>
        <Text style={styles.compareArrow}>↗</Text>
      </Pressable> : null}
      <ProductCompareSheet
        visible={compareOpen}
        products={ordered}
        candidateOrder={candidateOrder}
        evidence={evidence}
        selectedProductId={selectedProductId}
        onSelectProduct={onSelectProduct}
        disabledActions={disabledActions}
        onClose={() => setCompareOpen(false)}
      />
      {loading ? (
        <View style={styles.status} accessibilityRole="progressbar" accessibilityLabel={t('chat.productLoading')}>
          <ActivityIndicator color={theme.colors.rose} size="small" />
          <Text style={styles.statusText}>{t('chat.productLoading')}</Text>
        </View>
      ) : failed ? (
        <View style={[styles.status, styles.errorStatus]}>
          <Text style={styles.statusText} accessibilityRole="alert">{t('chat.productLoadFailed')}</Text>
          <Pressable accessibilityRole="button" onPress={onRetry} style={styles.retry}>
            <Text style={styles.link}>{t('chat.productRetry')}</Text>
          </Pressable>
        </View>
      ) : missingCount > 0 ? (
        <View style={styles.status}><Text style={styles.statusText}>{t('chat.productMissing', { count: missingCount })}</Text></View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  list: { gap: 8, marginTop: 12 },
  group: { gap: 10 },
  carouselRail: { gap: 12, paddingRight: 24 },
  compareOpen: { borderWidth: 1, borderColor: theme.colors.border, borderRadius: theme.radius.md, paddingHorizontal: 14,
    minHeight: theme.hitTarget, backgroundColor: theme.colors.card, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  compareOpenText: { color: theme.colors.roseDark, fontSize: theme.font.small, fontWeight: '700' },
  compareArrow: { color: theme.colors.rose, fontSize: 18 },
  missingCard: { minHeight: 160, borderWidth: 1, borderColor: theme.colors.border, backgroundColor: theme.colors.cream, borderRadius: theme.radius.lg, padding: 16, gap: 12, justifyContent: 'center' },
  carouselHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', minHeight: 34 },
  carouselCount: { color: theme.colors.roseDark, fontSize: theme.font.caption, fontWeight: '700' },
  carouselNavigation: { flexDirection: 'row', gap: 8 },
  carouselArrow: { width: 36, height: 36, borderRadius: 18, backgroundColor: theme.colors.roseSoft, alignItems: 'center', justifyContent: 'center' },
  carouselArrowText: { color: theme.colors.rose, fontSize: 23, lineHeight: 28 },
  groupTitle: { color: theme.colors.ink, fontSize: theme.font.small, fontWeight: '700', marginTop: 4 },
  card: { backgroundColor: theme.colors.card, borderColor: theme.colors.border, borderRadius: theme.radius.lg, borderWidth: 1, gap: 10, padding: 12 },
  compoundPriceRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
  priceToggle: { minHeight: theme.hitTarget, justifyContent: 'center', paddingHorizontal: 8 },
  cardSelected: { borderColor: theme.colors.rose, borderWidth: 2 },
  selectProduct: { borderColor: theme.colors.rose, borderWidth: 1, minHeight: theme.hitTarget, borderRadius: theme.radius.pill, justifyContent: 'center', alignItems: 'center' },
  selectProductActive: { backgroundColor: theme.colors.rose },
  selectProductText: { color: theme.colors.rose, fontWeight: '700', fontSize: theme.font.small },
  selectProductTextActive: { color: theme.colors.white },
  productHeader: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  productBody: { gap: 7 },
  image: { width: 92, height: 104, borderRadius: theme.radius.md, backgroundColor: theme.colors.roseSoft },
  details: { flex: 1, gap: 5 },
  brand: { color: theme.colors.inkMuted, fontSize: theme.font.caption, fontWeight: '700' },
  name: { color: theme.colors.ink, fontSize: theme.font.body, fontWeight: '700', lineHeight: 21 },
  price: { color: theme.colors.ink, fontSize: theme.font.body, fontWeight: '700', marginTop: 3 },
  ingredientBlock: { backgroundColor: theme.colors.cream, borderRadius: theme.radius.sm, gap: 4, padding: 10 },
  conditionPanel: { backgroundColor: theme.colors.surface, borderColor: theme.colors.border, borderRadius: theme.radius.md, borderWidth: 1, padding: 10, gap: 5 },
  sectionTitle: { color: theme.colors.ink, fontSize: theme.font.caption, fontWeight: '700' },
  conditionRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  conditionDetail: { flex: 1, gap: 2 },
  conditionLabel: { color: theme.colors.ink, fontSize: theme.font.caption, lineHeight: 19 },
  conditionBasis: { color: theme.colors.inkMuted, fontSize: theme.font.caption },
  conditionStatus: { fontSize: theme.font.caption, fontWeight: '700', lineHeight: 19, flexShrink: 1, textAlign: 'right' },
  conditionMet: { color: theme.colors.success },
  conditionNotMet: { color: theme.colors.danger },
  conditionUnknown: { color: theme.colors.warning },
  notice: { color: theme.colors.inkMuted, fontSize: theme.font.caption, lineHeight: 17 },
  link: { color: theme.colors.rose, fontSize: theme.font.caption, fontWeight: '700' },
  actions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  open: { flexGrow: 1, minHeight: 44, justifyContent: 'center', alignItems: 'center', borderColor: theme.colors.border, borderWidth: 1, borderRadius: theme.radius.pill, paddingHorizontal: 12 },
  arButton: { flexGrow: 1, minHeight: 44, alignItems: 'center', justifyContent: 'center', backgroundColor: theme.colors.rose, borderRadius: theme.radius.pill, paddingHorizontal: 12 },
  arButtonText: { color: theme.colors.white, fontSize: theme.font.caption, fontWeight: '700', textAlign: 'center' },
  shades: { flexDirection: 'row', gap: 6 },
  shade: { minHeight: 44, flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 8, borderWidth: 1, borderColor: theme.colors.border, borderRadius: theme.radius.sm },
  shadeSelected: { borderColor: theme.colors.rose, backgroundColor: theme.colors.roseSoft },
  swatch: { width: 16, height: 16, borderRadius: 8, borderWidth: 1, borderColor: theme.colors.border },
  shadeText: { color: theme.colors.ink, fontSize: theme.font.caption },
  status: { alignItems: 'center', flexDirection: 'row', flexWrap: 'wrap', gap: 8, backgroundColor: theme.colors.cream, borderRadius: theme.radius.md, paddingHorizontal: 12, paddingVertical: 8 },
  errorStatus: { backgroundColor: theme.colors.warningBg },
  statusText: { color: theme.colors.inkMuted, fontSize: theme.font.caption, lineHeight: 18 },
  retry: { minHeight: 44, justifyContent: 'center', paddingHorizontal: 4 },
  pressed: { opacity: 0.8 },
  disabled: { opacity: 0.45 },
});
