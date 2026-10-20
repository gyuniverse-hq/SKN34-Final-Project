import Ionicons from '@expo/vector-icons/Ionicons';
import { useRouter } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Button } from '@/components/ui/Button';
import { EmptyState, LoadingState } from '@/components/ui/StateViews';
import { theme } from '@/constants/theme';
import { useCartLines } from '@/hooks/useCartLines';
import { createId, formatKRW } from '@/lib/format';
import { useI18n } from '@/lib/i18n';
import { mapsUrl } from '@/lib/maps';
import { useStores } from '@/lib/queries';
import { useCartStore } from '@/store/cartStore';
import { useShoppingListStore } from '@/store/shoppingListStore';
import type { ShoppingList } from '@/types';

export default function CheckoutScreen() {
  const router = useRouter();
  const { t } = useI18n();
  const { lines, total, query } = useCartLines();
  const stores = useStores();
  const clearCart = useCartStore((s) => s.clear);
  const saveList = useShoppingListStore((s) => s.save);
  const [storeId, setStoreId] = useState<string | undefined>();

  if (query.isPending) return <LoadingState />;
  if (lines.length === 0) {
    return <EmptyState icon="cart-outline" title={t('checkout.empty')} />;
  }

  const onSave = () => {
    const list: ShoppingList = {
      id: createId('L'),
      createdAt: new Date().toISOString(),
      storeId,
      totalKRW: total,
      lines: lines.map((l) => ({
        productId: l.product.id,
        shadeId: l.shade?.id,
        quantity: l.item.quantity,
        unitPriceKRW: l.product.priceKRW,
        brand: l.product.brand,
        name: l.product.name,
        nameKo: l.product.nameKo,
        shadeName: l.shade?.name,
      })),
    };
    saveList(list);
    clearCart();
    router.dismissAll();
    router.push(`/lists/${list.id}`);
  };

  return (
    <SafeAreaView style={styles.screen} edges={['bottom']}>
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.intro}>{t('checkout.intro')}</Text>

        <Text style={styles.heading}>{t('checkout.chooseStore')}</Text>
        <StoreOption label={t('checkout.anyStore')} selected={!storeId} onPress={() => setStoreId(undefined)} />
        {stores.data?.map((store) => (
          <StoreOption
            key={store.id}
            label={store.name}
            detail={`${store.district} · ${store.hours}`}
            selected={storeId === store.id}
            onPress={() => setStoreId(store.id)}
            onMap={() => WebBrowser.openBrowserAsync(mapsUrl(store))}
            mapLabel={t('checkout.openMap')}
          />
        ))}

        <View style={styles.summary}>
          {lines.map((l) => (
            <View key={l.key} style={styles.summaryRow}>
              <Text style={styles.summaryName} numberOfLines={1}>
                {l.product.brand} {l.product.name}
                {l.shade ? ` · ${l.shade.name}` : ''} × {l.item.quantity}
              </Text>
              <Text style={styles.summaryPrice}>{formatKRW(l.lineTotal)}</Text>
            </View>
          ))}
          <View style={[styles.summaryRow, styles.totalRow]}>
            <Text style={styles.totalLabel}>{t('cart.subtotal')}</Text>
            <Text style={styles.totalValue}>{formatKRW(total)}</Text>
          </View>
          <Text style={styles.priceNote}>{t('cart.priceNote')}</Text>
        </View>
      </ScrollView>
      <View style={styles.footer}>
        <Button label={t('checkout.save')} icon="list-outline" onPress={onSave} />
      </View>
    </SafeAreaView>
  );
}

function StoreOption({
  label,
  detail,
  selected,
  onPress,
  onMap,
  mapLabel,
}: {
  label: string;
  detail?: string;
  selected: boolean;
  onPress: () => void;
  onMap?: () => void;
  mapLabel?: string;
}) {
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="radio"
      accessibilityState={{ checked: selected }}
      style={[styles.store, selected && styles.storeSelected]}>
      <Ionicons
        name={selected ? 'radio-button-on' : 'radio-button-off'}
        size={20}
        color={selected ? theme.colors.rose : theme.colors.inkFaint}
      />
      <View style={{ flex: 1 }}>
        <Text style={styles.storeName}>{label}</Text>
        {detail ? <Text style={styles.storeDetail}>{detail}</Text> : null}
      </View>
      {onMap ? (
        <Pressable onPress={onMap} hitSlop={8} accessibilityRole="link" accessibilityLabel={mapLabel}>
          <Ionicons name="map-outline" size={20} color={theme.colors.inkMuted} />
        </Pressable>
      ) : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  content: { padding: theme.spacing.lg, paddingBottom: 32 },
  intro: { fontSize: theme.font.body, color: theme.colors.inkMuted, lineHeight: 22, marginBottom: 20 },
  heading: { fontSize: theme.font.body, fontWeight: '700', color: theme.colors.ink, marginBottom: 10 },
  store: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    padding: 14,
    borderRadius: theme.radius.md,
    borderWidth: 1,
    borderColor: theme.colors.border,
    backgroundColor: theme.colors.card,
    marginBottom: 8,
  },
  storeSelected: { borderColor: theme.colors.rose },
  storeName: { fontSize: theme.font.small, fontWeight: '700', color: theme.colors.ink },
  storeDetail: { fontSize: 12, color: theme.colors.inkMuted, marginTop: 2 },
  summary: {
    marginTop: 20,
    padding: 16,
    borderRadius: theme.radius.md,
    backgroundColor: theme.colors.card,
    gap: 8,
    ...theme.shadow,
  },
  summaryRow: { flexDirection: 'row', justifyContent: 'space-between', gap: 12 },
  summaryName: { flex: 1, fontSize: theme.font.small, color: theme.colors.ink },
  summaryPrice: { fontSize: theme.font.small, fontWeight: '600', color: theme.colors.ink },
  totalRow: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: theme.colors.border, paddingTop: 10, marginTop: 4 },
  totalLabel: { fontSize: theme.font.body, color: theme.colors.inkMuted },
  totalValue: { fontSize: theme.font.title, fontWeight: '800', color: theme.colors.ink },
  priceNote: { fontSize: 11, color: theme.colors.inkFaint },
  footer: {
    paddingHorizontal: theme.spacing.lg,
    paddingTop: 12,
    paddingBottom: 8,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: theme.colors.border,
  },
});
