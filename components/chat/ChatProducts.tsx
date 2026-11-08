import { useRef, useState } from 'react';
import { Image } from 'expo-image';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { ProductImage } from '@/components/ui/ProductImage';
import { theme } from '@/constants/theme';
import { canTryOn } from '@/lib/catalog';
import type { ChatCondition } from '@/lib/chatConditions';
import { formatKRW } from '@/lib/format';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import { parseCategory, parseId } from '@/lib/routes';
import type { ChatProductEvidence, Product } from '@/types';

interface Props {
  products: Product[];
  loading: boolean;
  failed: boolean;
  missingCount: number;
  conditions: ChatCondition[];
  showIngredients: boolean;
  onRetry: () => void;
  onOpenProduct: (id: string, shadeId?: string) => void;
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

export function ChatProducts({ products, loading, failed, missingCount, conditions, showIngredients, onRetry, onOpenProduct, onOpenAr, disabledActions = false, previewImage, candidateOrder, evidence, selectedShades: controlledShades, onSelectShade, onSelectProduct, selectedProductId, expectedIds }: Props) {
  const { t } = useI18n();
  const [selectedShades, setSelectedShades] = useState<Record<string, string>>({});
  const requiredConditions = conditions.filter((condition) => condition.required);
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
  const slides = orderedExpected
    ? orderedExpected.map((id) => loadedSlides.find((slide) => slide.key === id) ?? { key: id, title: undefined, products: [] })
    : loadedSlides;
  const { width: screenWidth } = useWindowDimensions();
  const cardWidth = Math.min(312, Math.max(224, screenWidth - 96));
  const slideStep = cardWidth + 12;
  const carouselRef = useRef<ScrollView>(null);
  const [viewedIndex, setViewedIndex] = useState(0);
  const currentIndex = Math.min(viewedIndex, Math.max(0, slides.length - 1));
  const goTo = (index: number) => {
    const next = Math.max(0, Math.min(index, slides.length - 1));
    setViewedIndex(next);
    carouselRef.current?.scrollTo?.({ x: next * slideStep, animated: true });
  };

  return (
    <View style={styles.list}>
      {conditions.length && products.length ? <Text style={styles.notice}>{t('chat.ui.partialConditionsNotice' as TranslationKey)}</Text> : null}
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
      {slides.map((group) => (
        <View key={group.key} style={[styles.group, { width: cardWidth }]}>
          {group.title ? <Text style={styles.groupTitle}>{t(group.title)}</Text> : null}
          {!group.products.length ? <View style={styles.missingCard}>
            <Text style={styles.carouselCount}>{candidateOrder?.includes(group.key)
              ? t('chat.candidateNumber', { index: candidateOrder.indexOf(group.key) + 1 })
              : t('chat.conditionUnknown')}</Text>
            <Text style={styles.notice}>{loading ? t('chat.productLoading') : failed
              ? t('chat.productLoadFailed') : t('chat.productMissing', { count: 1 })}</Text>
          </View> : null}
          {group.products.map((product) => {
            const candidateIndex = candidateOrder?.indexOf(product.id) ?? -1;
            const proof = evidence?.find((item) => item.productId === product.id);
            const validShades = parseId(product.id) === product.id
              ? product.shades.filter((shade) => parseId(shade.id) === shade.id) : [];
            const tryOn = canTryOn(product) && parseId(product.id) === product.id && validShades.length > 0;
            const selectedShade = validShades.find((shade) => shade.id === (controlledShades ?? selectedShades)[product.id]);
            const productCategory = parseCategory(product.category);
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
                    <Text style={styles.price}>{t('chat.referencePrice')} {Number.isFinite(product.priceKRW) && product.priceKRW > 0 ? formatKRW(product.priceKRW) : t('chat.conditionUnknown')}</Text>
                  </View>
                </View>
                <View style={styles.productBody}>
                  {proof ? <View style={styles.ingredientBlock}>
                    <Text style={styles.notice}>{t('chat.catalogEvidence')}</Text>
                    <Text style={styles.notice}>{t(proof.ingredientCoverage === 'key_only'
                      ? 'chat.keyOnlyEvidence' : 'chat.noIngredientEvidence')}</Text>
                  </View> : null}
                  {showIngredients ? (
                    <View style={styles.ingredientBlock}>
                      {product.keyIngredients.length > 0 ? (
                        <>
                          <Text style={styles.notice}>{t('product.keyIngredients')}: {product.keyIngredients.join(', ')}</Text>
                          <Text style={styles.notice}>{t('chat.ui.keyIngredientsNotice')}</Text>
                        </>
                      ) : <Text style={styles.notice}>{t('chat.ui.ingredientUnavailable')}</Text>}
                    </View>
                  ) : null}
                  {conditions.length ? (
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
                  {validShades.length > 0 ? (
                    <>
                      <Text style={styles.notice}>{t('chat.selectShade')}</Text>
                      <ScrollView horizontal showsHorizontalScrollIndicator contentContainerStyle={styles.shades}>
                        {validShades.map((shade) => (
                          <Pressable
                            key={shade.id}
                            accessibilityRole="button"
                            accessibilityLabel={`${product.name}, ${shade.name}`}
                            accessibilityState={{ selected: shade.id === selectedShade?.id, disabled: disabledActions }}
                            disabled={disabledActions}
                            onPress={() => {
                              if (disabledActions) return;
                              setSelectedShades((current) => ({ ...current, [product.id]: shade.id }));
                              onSelectShade?.(product.id, shade.id);
                            }}
                            style={[styles.shade, shade.id === selectedShade?.id && styles.shadeSelected]}>
                            <View style={[styles.swatch, { backgroundColor: shade.hex }]} />
                            <Text style={styles.shadeText}>{shade.name}</Text>
                          </Pressable>
                        ))}
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
                      onPress={disabledActions ? undefined : () => onOpenProduct(product.id, selectedShade?.id)}
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
  missingCard: { minHeight: 160, borderWidth: 1, borderColor: theme.colors.border, backgroundColor: theme.colors.cream, borderRadius: theme.radius.lg, padding: 16, gap: 12, justifyContent: 'center' },
  carouselHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', minHeight: 34 },
  carouselCount: { color: theme.colors.roseDark, fontSize: theme.font.caption, fontWeight: '700' },
  carouselNavigation: { flexDirection: 'row', gap: 8 },
  carouselArrow: { width: 36, height: 36, borderRadius: 18, backgroundColor: theme.colors.roseSoft, alignItems: 'center', justifyContent: 'center' },
  carouselArrowText: { color: theme.colors.rose, fontSize: 23, lineHeight: 28 },
  groupTitle: { color: theme.colors.ink, fontSize: theme.font.small, fontWeight: '700', marginTop: 4 },
  card: { backgroundColor: theme.colors.card, borderColor: theme.colors.border, borderRadius: theme.radius.lg, borderWidth: 1, gap: 10, padding: 12 },
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
