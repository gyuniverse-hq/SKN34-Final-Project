import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { ProductImage } from '@/components/ui/ProductImage';
import { theme } from '@/constants/theme';
import { formatKRW } from '@/lib/format';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import { parseCategory, parseId } from '@/lib/routes';
import type { ChatProductEvidence, Product } from '@/types';

type Props = {
  visible: boolean;
  products: Product[];
  candidateOrder?: string[];
  evidence?: ChatProductEvidence[];
  selectedProductId?: string | null;
  onSelectProduct?: (productId: string) => void;
  onClose: () => void;
  disabledActions?: boolean;
};

/**
 * Product facts only: this sheet must never infer real-world color, skin suitability,
 * verified fragrance absence or ingredient effectiveness from catalog tags.
 */
export function ProductCompareSheet({
  visible, products, candidateOrder, evidence, selectedProductId,
  onSelectProduct, onClose, disabledActions = false,
}: Props) {
  const { t } = useI18n();
  const ordered = candidateOrder
    ? [...products].sort((a, b) => {
        const rank = (id: string) => {
          const index = candidateOrder.indexOf(id);
          return index < 0 ? candidateOrder.length : index;
        };
        return rank(a.id) - rank(b.id);
      })
    : products;

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}
      accessibilityViewIsModal>
      <View style={styles.backdrop}>
        <Pressable accessibilityRole="button" accessibilityLabel={t('chat.compare.close')}
          onPress={onClose} style={StyleSheet.absoluteFill} />
        <View style={styles.sheet}>
          <View style={styles.handle} />
          <View style={styles.header}>
            <View style={styles.heading}>
              <Text accessibilityRole="header" style={styles.title}>{t('chat.compare.title')}</Text>
              <Text style={styles.subtitle}>{t('chat.compare.count', { count: ordered.length })}</Text>
            </View>
            <Pressable accessibilityRole="button" accessibilityLabel={t('chat.compare.close')}
              onPress={onClose} style={styles.closeButton}>
              <Text style={styles.closeIcon}>×</Text>
            </Pressable>
          </View>
          <Text style={styles.notice}>{t('chat.compare.notice')}</Text>
          <ScrollView style={styles.comparisonScroll} nestedScrollEnabled
            contentContainerStyle={styles.comparisonVertical}>
            <ScrollView horizontal nestedScrollEnabled showsHorizontalScrollIndicator={false}
              testID="chat-product-compare-columns" contentContainerStyle={styles.columns}>
            {ordered.map((product) => {
              const index = candidateOrder?.indexOf(product.id) ?? -1;
              const proof = evidence?.find((item) => item.productId === product.id);
              const valid = parseId(product.id) === product.id;
              return <View key={product.id} style={[styles.column, selectedProductId === product.id && styles.selectedColumn]}>
                <View style={styles.productHead}>
                  <ProductImage uri={product.imageUrl} category={parseCategory(product.category)}
                    recyclingKey={product.id} style={styles.productImage} />
                  <Text style={styles.number}>{index >= 0 ? t('chat.candidateNumber', { index: index + 1 }) : ''}</Text>
                  <Text style={styles.brand} numberOfLines={1}>{product.brand}</Text>
                  <Text style={styles.productName} numberOfLines={2}>{product.name}</Text>
                </View>
                <View style={styles.field}>
                  <Text style={styles.label}>{t('chat.compare.price')}</Text>
                  <Text style={styles.value}>{Number.isFinite(product.priceKRW) && product.priceKRW > 0
                    ? formatKRW(product.priceKRW) : t('chat.conditionUnknown')}</Text>
                </View>
                <View style={styles.field}>
                  <Text style={styles.label}>{t('chat.compare.finish')}</Text>
                  <Text style={styles.value}>{product.texture
                    ? t(`ar.texture.${product.texture}` as TranslationKey)
                    : t('chat.conditionUnknown')}</Text>
                </View>
                <View style={styles.field}>
                  <Text style={styles.label}>{t('chat.compare.shades')}</Text>
                  <Text style={styles.value}>{t('chat.compare.shadeCount', { count: product.shades.length })}</Text>
                  <View style={styles.swatches}>{product.shades.slice(0, 5).map((shade) => (
                    <View key={shade.id} style={[styles.swatch, { backgroundColor: shade.hex }]} />
                  ))}</View>
                </View>
                <View style={styles.field}>
                  <Text style={styles.label}>{t('chat.compare.ingredients')}</Text>
                  <Text style={styles.value}>{proof?.ingredientCoverage === 'key_only'
                    ? t('chat.compare.keyOnly') : t('chat.compare.unverified')}</Text>
                  <Text style={styles.subvalue} numberOfLines={3}>
                    {product.keyIngredients.length ? product.keyIngredients.slice(0, 3).join(', ')
                      : t('chat.compare.noKeyIngredients')}
                  </Text>
                </View>
                {onSelectProduct && valid ? (
                  <Pressable accessibilityRole="button"
                    accessibilityLabel={`${t('chat.carousel.choose')}: ${product.name}`}
                    accessibilityState={{ selected: selectedProductId === product.id, disabled: disabledActions }}
                    disabled={disabledActions}
                    onPress={() => { onSelectProduct(product.id); onClose(); }}
                    style={[styles.selectButton, selectedProductId === product.id && styles.selectedButton]}>
                    <Text style={[styles.selectText, selectedProductId === product.id && styles.selectedText]}>
                      {t(selectedProductId === product.id ? 'chat.carousel.chosen' : 'chat.carousel.choose')}
                    </Text>
                  </Pressable>
                ) : null}
              </View>;
            })}
            </ScrollView>
          </ScrollView>
          <Text style={styles.footer}>{t('chat.compare.footer')}</Text>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, justifyContent: 'flex-end', backgroundColor: theme.colors.overlay },
  sheet: { backgroundColor: theme.colors.surface, borderTopLeftRadius: 24, borderTopRightRadius: 24,
    paddingTop: 10, paddingBottom: 30, maxHeight: '88%', minHeight: 360 },
  handle: { alignSelf: 'center', width: 42, height: 5, borderRadius: 3, backgroundColor: theme.colors.border },
  header: { paddingHorizontal: 18, paddingTop: 16, paddingBottom: 8, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  heading: { flex: 1, gap: 3 },
  title: { color: theme.colors.ink, fontSize: theme.font.h2, fontWeight: '800' },
  subtitle: { color: theme.colors.inkMuted, fontSize: theme.font.caption },
  closeButton: { width: 44, height: 44, borderRadius: 22, backgroundColor: theme.colors.roseSoft, alignItems: 'center', justifyContent: 'center' },
  closeIcon: { color: theme.colors.roseDark, fontSize: 26, lineHeight: 30 },
  notice: { color: theme.colors.inkMuted, fontSize: theme.font.caption, lineHeight: 18, marginHorizontal: 18, marginBottom: 14 },
  comparisonScroll: { flexShrink: 1 },
  comparisonVertical: { paddingBottom: 8 },
  columns: { gap: 10, paddingHorizontal: 18, paddingBottom: 8 },
  column: { width: 184, borderWidth: 1, borderColor: theme.colors.border, backgroundColor: theme.colors.card, borderRadius: 16, overflow: 'hidden', padding: 12, gap: 12 },
  selectedColumn: { borderColor: theme.colors.rose },
  productHead: { minHeight: 168, gap: 3 },
  productImage: { width: 78, height: 78, alignSelf: 'center', borderRadius: theme.radius.sm, backgroundColor: theme.colors.cream },
  number: { color: theme.colors.rose, fontSize: theme.font.caption, fontWeight: '700', marginTop: 3 },
  brand: { color: theme.colors.inkMuted, fontSize: theme.font.caption },
  productName: { color: theme.colors.ink, fontSize: theme.font.small, fontWeight: '700', lineHeight: 19 },
  field: { minHeight: 66, borderTopColor: theme.colors.border, borderTopWidth: 1, paddingTop: 10, gap: 5 },
  label: { fontSize: theme.font.caption, color: theme.colors.inkMuted, fontWeight: '700' },
  value: { fontSize: theme.font.small, color: theme.colors.ink, lineHeight: 19 },
  subvalue: { fontSize: theme.font.caption, color: theme.colors.inkMuted, lineHeight: 17 },
  swatches: { flexDirection: 'row', gap: 5, marginTop: 3, flexWrap: 'wrap' },
  swatch: { height: 13, width: 13, borderRadius: 7, borderWidth: 1, borderColor: theme.colors.border },
  selectButton: { borderColor: theme.colors.rose, borderWidth: 1, backgroundColor: theme.colors.card, borderRadius: 24, minHeight: theme.hitTarget, alignItems: 'center', justifyContent: 'center', marginTop: 'auto' },
  selectedButton: { backgroundColor: theme.colors.rose },
  selectText: { color: theme.colors.rose, fontSize: theme.font.small, fontWeight: '700' },
  selectedText: { color: theme.colors.white },
  footer: { fontSize: theme.font.caption, color: theme.colors.inkMuted, lineHeight: 19, paddingHorizontal: 18, paddingTop: 12 },
});
