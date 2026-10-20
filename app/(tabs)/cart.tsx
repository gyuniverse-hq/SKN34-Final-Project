import { Image } from 'expo-image';
import { useRouter } from 'expo-router';
import { FlatList, Pressable, StyleSheet, Text, View } from 'react-native';
import { Button } from '@/components/ui/Button';
import { QuantityStepper } from '@/components/ui/QuantityStepper';
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/StateViews';
import { theme } from '@/constants/theme';
import { useCartLines } from '@/hooks/useCartLines';
import { confirmAction } from '@/lib/confirm';
import { formatKRW } from '@/lib/format';
import { useI18n } from '@/lib/i18n';
import { MAX_QUANTITY, useCartStore } from '@/store/cartStore';

export default function CartScreen() {
  const router = useRouter();
  const { t } = useI18n();
  const { items, lines, total, query } = useCartLines();
  const setQuantity = useCartStore((s) => s.setQuantity);
  const clear = useCartStore((s) => s.clear);

  if (items.length === 0) {
    return (
      <View style={styles.screen}>
        <EmptyState
          icon="cart-outline"
          title={t('cart.empty')}
          body={t('cart.emptyBody')}
          action={<Button label={t('cart.goShop')} onPress={() => router.navigate('/')} />}
        />
      </View>
    );
  }
  if (query.isPending) return <LoadingState />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />;

  return (
    <View style={styles.screen}>
      <FlatList
        data={lines}
        keyExtractor={(l) => l.key}
        contentContainerStyle={styles.list}
        renderItem={({ item: line }) => (
          <View style={styles.row}>
            <Pressable
              onPress={() => router.push(`/product/${line.product.id}`)}
              accessibilityRole="button"
              accessibilityLabel={`${line.product.brand} ${line.product.name}`}>
              <Image source={{ uri: line.product.imageUrl }} style={styles.thumb} contentFit="cover" />
            </Pressable>
            <View style={styles.info}>
              <Text style={styles.brand}>{line.product.brand}</Text>
              <Text style={styles.name} numberOfLines={2}>
                {line.product.name}
              </Text>
              {line.shade ? (
                <View style={styles.shadeRow}>
                  <View style={[styles.shadeDot, { backgroundColor: line.shade.hex }]} />
                  <Text style={styles.shadeName}>{line.shade.name}</Text>
                </View>
              ) : null}
              {line.item.addedFromLookId ? <Text style={styles.fromLook}>{t('cart.fromLook')}</Text> : null}
              <View style={styles.bottomRow}>
                <QuantityStepper
                  value={line.item.quantity}
                  max={MAX_QUANTITY}
                  onChange={(q) => setQuantity(line.key, q)}
                />
                <Text style={styles.price}>{formatKRW(line.lineTotal)}</Text>
              </View>
            </View>
          </View>
        )}
        ListFooterComponent={
          <Button
            label={t('cart.clear')}
            variant="ghost"
            compact
            onPress={() => confirmAction(t('cart.clear'), t('common.delete'), t('common.cancel'), clear)}
          />
        }
      />
      <View style={styles.footer}>
        <View style={styles.totalRow}>
          <Text style={styles.totalLabel}>{t('cart.subtotal')}</Text>
          <Text style={styles.totalValue}>{formatKRW(total)}</Text>
        </View>
        <Text style={styles.priceNote}>{t('cart.priceNote')}</Text>
        <Button label={t('cart.shopInStore')} icon="storefront-outline" onPress={() => router.push('/checkout')} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  list: { padding: theme.spacing.lg, gap: 12 },
  row: {
    flexDirection: 'row',
    gap: 12,
    backgroundColor: theme.colors.card,
    borderRadius: theme.radius.md,
    padding: 12,
    ...theme.shadow,
  },
  thumb: { width: 84, height: 84, borderRadius: theme.radius.sm, backgroundColor: theme.colors.surfaceAlt },
  info: { flex: 1, gap: 2 },
  brand: { fontSize: 11, color: theme.colors.inkMuted, textTransform: 'uppercase', letterSpacing: 0.5 },
  name: { fontSize: theme.font.small, fontWeight: '600', color: theme.colors.ink },
  shadeRow: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 2 },
  shadeDot: { width: 10, height: 10, borderRadius: 5 },
  shadeName: { fontSize: 12, color: theme.colors.inkMuted },
  fromLook: { fontSize: 11, color: theme.colors.rose, fontWeight: '600' },
  bottomRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: 8 },
  price: { fontSize: theme.font.body, fontWeight: '700', color: theme.colors.ink },
  footer: {
    padding: theme.spacing.lg,
    gap: 6,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: theme.colors.border,
    backgroundColor: theme.colors.card,
  },
  totalRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'baseline' },
  totalLabel: { fontSize: theme.font.body, color: theme.colors.inkMuted },
  totalValue: { fontSize: theme.font.h2, fontWeight: '800', color: theme.colors.ink },
  priceNote: { fontSize: 11, color: theme.colors.inkFaint, marginBottom: 8 },
});
