import { useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';
import { ProductImage } from '@/components/ui/ProductImage';
import { theme } from '@/constants/theme';
import { canTryOn } from '@/lib/catalog';
import type { ChatCondition } from '@/lib/chatConditions';
import { formatKRW } from '@/lib/format';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import { parseId } from '@/lib/routes';
import type { Product } from '@/types';

interface Props {
  products: Product[];
  loading: boolean;
  failed: boolean;
  missingCount: number;
  conditions: ChatCondition[];
  showIngredients: boolean;
  onRetry: () => void;
  onOpenProduct: (id: string) => void;
  onOpenAr: (productId: string, shadeId: string) => void;
}

export function ChatProducts({ products, loading, failed, missingCount, conditions, showIngredients, onRetry, onOpenProduct, onOpenAr }: Props) {
  const { t } = useI18n();
  const [selectedShades, setSelectedShades] = useState<Record<string, string>>({});

  return (
    <View style={styles.list}>
      {products.map((product) => {
        const validShades = product.shades.filter((shade) => parseId(shade.id) === shade.id);
        const tryOn = canTryOn(product) && parseId(product.id) === product.id && validShades.length > 0;
        const selectedShade = validShades.find((shade) => shade.id === selectedShades[product.id]);
        return (
        <View key={product.id} style={styles.card}>
          <ProductImage uri={product.imageUrl} category={product.category} recyclingKey={product.id} style={styles.image} compact />
          <View style={styles.details}>
            <Text style={styles.brand}>{product.brand}</Text>
            <Text style={styles.name}>{product.name}</Text>
            <Text style={styles.notice}>{t(`shop.cat.${product.category}` as TranslationKey)}</Text>
            <Text style={styles.price}>{t('chat.referencePrice')} {formatKRW(product.priceKRW)}</Text>
            {showIngredients && product.keyIngredients.length > 0 ? (
              <>
                <Text style={styles.notice}>{t('product.keyIngredients')}: {product.keyIngredients.join(', ')}</Text>
                <Text style={styles.notice}>{t('chat.ui.keyIngredientsNotice')}</Text>
              </>
            ) : null}
            {conditions.map((condition, index) => {
              const matches = condition.kind === 'category' && typeof condition.value === 'string'
                ? product.category === condition.value
                : condition.kind === 'maxPrice' && typeof condition.value === 'number' && Number.isFinite(condition.value) && condition.value >= 0 && Number.isFinite(product.priceKRW) && product.priceKRW >= 0
                  ? product.priceKRW <= condition.value
                  : undefined;
              return (
                <Text key={`${condition.kind}-${index}`} style={styles.notice}>
                  {condition.text} · {t(matches === undefined ? 'chat.conditionUnknown' : matches ? 'chat.conditionMet' : 'chat.conditionNotMet')}
                  {condition.kind === 'maxPrice' ? ` (${t('chat.conditionPriceBasis')})` : ''}
                </Text>
              );
            })}
            {tryOn ? (
              <>
                <Text style={styles.notice}>{t('chat.selectShade')}</Text>
                <View style={styles.shades}>
                  {validShades.map((shade) => (
                    <Pressable
                      key={shade.id}
                      accessibilityRole="button"
                      accessibilityState={{ selected: shade.id === selectedShade?.id }}
                      onPress={() => setSelectedShades((current) => ({ ...current, [product.id]: shade.id }))}
                      style={[styles.shade, shade.id === selectedShade?.id && styles.shadeSelected]}>
                      <View style={[styles.swatch, { backgroundColor: shade.hex }]} />
                      <Text style={styles.shadeText}>{shade.name}</Text>
                    </Pressable>
                  ))}
                </View>
                {selectedShade ? (
                  <Pressable
                    accessibilityRole="button"
                    onPress={() => onOpenAr(product.id, selectedShade.id)}
                    style={({ pressed }) => [styles.open, pressed && styles.pressed]}>
                    <Text style={styles.link}>{t('chat.trySelectedShade')}</Text>
                  </Pressable>
                ) : <Text style={styles.notice}>{t('chat.tryOnAtDetail')}</Text>}
              </>
            ) : null}
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={`${product.brand} ${product.name}, ${t('chat.openProduct')}`}
              onPress={() => onOpenProduct(product.id)}
              style={({ pressed }) => [styles.open, pressed && styles.pressed]}>
              <Text style={styles.link}>{t('chat.openProduct')} ›</Text>
            </Pressable>
          </View>
        </View>
        );
      })}
      {loading ? (
        <View style={styles.status} accessibilityRole="progressbar" accessibilityLabel={t('chat.productLoading')}>
          <ActivityIndicator color={theme.colors.rose} size="small" />
          <Text style={styles.statusText}>{t('chat.productLoading')}</Text>
        </View>
      ) : failed ? (
        <View style={styles.status}>
          <Text style={styles.statusText} accessibilityRole="alert">{t('chat.productLoadFailed')}</Text>
          <Pressable accessibilityRole="button" onPress={onRetry} style={styles.retry}>
            <Text style={styles.link}>{t('chat.productRetry')}</Text>
          </Pressable>
        </View>
      ) : missingCount > 0 ? (
        <Text style={styles.statusText}>{t('chat.productMissing', { count: missingCount })}</Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  list: { gap: 8, marginTop: 12 },
  card: { backgroundColor: theme.colors.card, borderColor: theme.colors.border, borderRadius: theme.radius.md, borderWidth: 1, flexDirection: 'row', gap: 10, padding: 10 },
  image: { width: 72, height: 88, borderRadius: theme.radius.sm },
  details: { flex: 1, gap: 3 },
  brand: { color: theme.colors.inkMuted, fontSize: theme.font.caption, fontWeight: '700' },
  name: { color: theme.colors.ink, fontSize: theme.font.small, fontWeight: '700', lineHeight: 19 },
  price: { color: theme.colors.ink, fontSize: theme.font.caption },
  notice: { color: theme.colors.inkMuted, fontSize: theme.font.caption, lineHeight: 17 },
  link: { color: theme.colors.rose, fontSize: theme.font.caption, fontWeight: '700' },
  open: { minHeight: 44, justifyContent: 'center', alignSelf: 'flex-start', paddingRight: 8 },
  shades: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  shade: { minHeight: 44, flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 8, borderWidth: 1, borderColor: theme.colors.border, borderRadius: theme.radius.sm },
  shadeSelected: { borderColor: theme.colors.rose, backgroundColor: theme.colors.roseSoft },
  swatch: { width: 16, height: 16, borderRadius: 8, borderWidth: 1, borderColor: theme.colors.border },
  shadeText: { color: theme.colors.ink, fontSize: theme.font.caption },
  status: { alignItems: 'center', flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  statusText: { color: theme.colors.inkMuted, fontSize: theme.font.caption, lineHeight: 18 },
  retry: { minHeight: 44, justifyContent: 'center', paddingHorizontal: 4 },
  pressed: { opacity: 0.8 },
});
