import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { Button } from '@/components/ui/Button';
import { ProductImage } from '@/components/ui/ProductImage';
import { theme } from '@/constants/theme';
import { formatKRW } from '@/lib/format';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import type { CompareLineView } from '@/types/view';

interface Props {
  lines: CompareLineView[];
  onOpen: (productId: string, shadeId?: string) => void;
  onAddToCart: (productId: string, shadeId?: string) => void;
  onRemove: (productId: string) => void;
}

/** One column per product; rows share the same order so values line up across columns. */
export function CompareTable({ lines, onOpen, onAddToCart, onRemove }: Props) {
  const { t } = useI18n();
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.row}>
      {lines.map(({ item, product, shade, availability }) => (
        <View key={item.productId} style={styles.column}>
          {product ? (
            <>
              <ProductImage uri={product.imageUrl} category={product.category} style={styles.image} compact />
              <Text style={styles.brand} numberOfLines={1}>
                {product.brand}
              </Text>
              <Text style={styles.name} numberOfLines={2}>
                {product.name}
              </Text>
              <Field label={t('compare.price')} value={formatKRW(product.priceKRW)} strong />
              <Field
                label={t('compare.shade')}
                value={availability === 'shade_unavailable' ? t('catalog.shadeUnavailable') : (shade?.name ?? '—')}
                swatch={shade?.hex}
              />
              <Field label={t('compare.texture')} value={product.texture ? t(`texture.${product.texture}` as TranslationKey) : '—'} />
              <Field label={t('compare.volume')} value={product.volume || '—'} />
              <Field label={t('compare.shadeCount')} value={String(product.shades.length)} />
              <Field label={t('product.keyIngredients')} value={product.keyIngredients.join(', ') || '—'} />
              <View style={styles.actions}>
                <Button label={t('compare.view')} variant="secondary" compact onPress={() => onOpen(product.id, shade?.id)} />
                <Button
                  label={t('product.addToCart')}
                  icon="cart-outline"
                  compact
                  disabled={availability !== 'available'}
                  onPress={() => onAddToCart(product.id, shade?.id)}
                />
              </View>
            </>
          ) : (
            <Text style={styles.unavailable}>{t('catalog.productUnavailable')}</Text>
          )}
          <Button label={t('common.remove')} variant="ghost" compact onPress={() => onRemove(item.productId)} />
        </View>
      ))}
    </ScrollView>
  );
}

function Field({ label, value, strong, swatch }: { label: string; value: string; strong?: boolean; swatch?: string }) {
  return (
    <View style={styles.field}>
      <Text style={styles.fieldLabel}>{label}</Text>
      <View style={styles.fieldValueRow}>
        {swatch ? <View style={[styles.swatch, { backgroundColor: swatch }]} /> : null}
        <Text style={[styles.fieldValue, strong && styles.strong]} numberOfLines={3}>
          {value}
        </Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { gap: 12, paddingHorizontal: theme.spacing.lg, paddingBottom: 8 },
  column: {
    width: 176,
    padding: 12,
    gap: 6,
    borderRadius: theme.radius.md,
    borderWidth: 1,
    borderColor: theme.colors.border,
    backgroundColor: theme.colors.card,
  },
  image: { width: '100%', aspectRatio: 1, borderRadius: theme.radius.sm, backgroundColor: theme.colors.surfaceAlt },
  brand: { fontSize: 11, fontWeight: '700', color: theme.colors.accent, marginTop: 4 },
  name: { fontSize: theme.font.small, fontWeight: '700', color: theme.colors.ink, minHeight: 36 },
  field: { gap: 2, paddingTop: 6, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: theme.colors.border, minHeight: 48 },
  fieldLabel: { fontSize: 11, color: theme.colors.inkFaint, fontWeight: '600' },
  fieldValueRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  fieldValue: { flex: 1, fontSize: 12, color: theme.colors.ink },
  strong: { fontSize: theme.font.body, fontWeight: '800' },
  swatch: { width: 12, height: 12, borderRadius: 6, borderWidth: 1, borderColor: 'rgba(0,0,0,0.08)' },
  actions: { gap: 6, marginTop: 6 },
  unavailable: { fontSize: theme.font.small, color: theme.colors.inkMuted, paddingVertical: 24, textAlign: 'center' },
});
