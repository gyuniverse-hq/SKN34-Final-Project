import { useRouter } from 'expo-router';
import { FlatList, Pressable, StyleSheet, Text, View } from 'react-native';
import { Button } from '@/components/ui/Button';
import { Mascot } from '@/components/ui/Mascot';
import { Notice } from '@/components/ui/Notice';
import { ProductImage } from '@/components/ui/ProductImage';
import { QuantityStepper } from '@/components/ui/QuantityStepper';
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/StateViews';
import { theme } from '@/constants/theme';
import { useCartLines } from '@/hooks/useCartLines';
import { confirmAction } from '@/lib/confirm';
import { useAuth } from '@/lib/auth';
import { formatKRW } from '@/lib/format';
import { useI18n } from '@/lib/i18n';
import { loginHref, productHref } from '@/lib/routes';
import { MAX_QUANTITY, useCartStore } from '@/store/cartStore';

export default function CartScreen() {
  const router = useRouter();
  const { t } = useI18n();
  const { user, ready } = useAuth();
  const { items, lines, unavailable, total, query } = useCartLines();
  const setQuantity = useCartStore((s) => s.setQuantity);
  const remove = useCartStore((s) => s.remove);
  const clear = useCartStore((s) => s.clear);

  if (items.length === 0) {
    return (
      <View style={styles.screen}>
        <EmptyState
          illustration={<Mascot size={110} speech={t('mascot.cartEmpty')} />}
          title={t('cart.empty')}
          body={t('cart.emptyBody')}
          action={<Button label={t('cart.goShop')} onPress={() => router.dismissTo('/shop')} />}
        />
      </View>
    );
  }
  if (query.isPending) return <LoadingState />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />;

  const changed =
    unavailable.length > 0 ? (
      <View style={styles.changed}>
        <Notice tone="warning" title={t('cart.changedTitle')} body={t('cart.changedBody')} />
        {unavailable.map((line) => (
          <View key={line.key} style={styles.changedRow}>
            <View style={styles.changedCopy}>
              <Text style={styles.name} numberOfLines={1}>
                {line.product ? `${line.product.brand} ${line.product.name}` : line.item.productId}
              </Text>
              <Text style={styles.changedReason}>
                {t(line.availability === 'shade_unavailable' ? 'catalog.shadeUnavailable' : 'catalog.productUnavailable')}
              </Text>
            </View>
            {line.product ? (
              <Button
                label={t('cart.pickShade')}
                variant="secondary"
                compact
                onPress={() => router.push(productHref(line.product!.id))}
              />
            ) : null}
            <Button label={t('common.remove')} variant="ghost" compact onPress={() => remove(line.key)} />
          </View>
        ))}
      </View>
    ) : undefined;

  return (
    <View style={styles.screen}>
      <FlatList
        data={lines}
        keyExtractor={(l) => l.key}
        contentContainerStyle={styles.list}
        ListHeaderComponent={changed}
        renderItem={({ item: line }) => (
          <View style={styles.row}>
            <Pressable
              onPress={() => router.push(productHref(line.product.id, line.shade?.id))}
              accessibilityRole="button"
              accessibilityLabel={`${line.product.brand} ${line.product.name}`}>
              <ProductImage uri={line.product.imageUrl} category={line.product.category} style={styles.thumb} compact />
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
              <Pressable
                onPress={() => router.push(productHref(line.product.id, line.shade?.id))}
                accessibilityRole="link"
                hitSlop={8}
                style={styles.sellerLink}>
                <Text style={styles.sellerText}>{t('cart.viewProduct')} ›</Text>
              </Pressable>
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
        <Button
          label={t('cart.checkout')}
          icon="card-outline"
          disabled={!ready || lines.length === 0}
          onPress={() => router.push(user ? '/checkout' : loginHref('checkout'))}
        />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  list: { padding: theme.spacing.lg, gap: 12 },
  changed: { gap: 8, marginBottom: 4 },
  changedRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    padding: 12,
    borderRadius: theme.radius.md,
    borderWidth: 1,
    borderColor: theme.colors.border,
    backgroundColor: theme.colors.card,
  },
  changedCopy: { flex: 1, gap: 2 },
  changedReason: { fontSize: 12, color: theme.colors.warning, fontWeight: '600' },
  row: {
    flexDirection: 'row',
    gap: 12,
    backgroundColor: theme.colors.card,
    borderRadius: theme.radius.md,
    borderWidth: 1,
    borderColor: theme.colors.border,
    padding: 12,
  },
  thumb: { width: 84, height: 84, borderRadius: theme.radius.sm, backgroundColor: theme.colors.surfaceAlt },
  info: { flex: 1, gap: 2 },
  brand: { fontSize: 11, color: theme.colors.accent, fontWeight: '700' },
  name: { fontSize: theme.font.small, fontWeight: '600', color: theme.colors.ink },
  shadeRow: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 2 },
  shadeDot: { width: 10, height: 10, borderRadius: 5 },
  shadeName: { fontSize: 12, color: theme.colors.inkMuted },
  fromLook: { fontSize: 11, color: theme.colors.rose, fontWeight: '600' },
  bottomRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: 8 },
  price: { fontSize: theme.font.body, fontWeight: '700', color: theme.colors.ink },
  sellerLink: { alignSelf: 'flex-start', marginTop: 6, minHeight: 28, justifyContent: 'center' },
  sellerText: { fontSize: 12, fontWeight: '700', color: theme.colors.rose },
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
