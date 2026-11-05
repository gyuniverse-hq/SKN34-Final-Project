import Ionicons from '@expo/vector-icons/Ionicons';
import { useLocalSearchParams, useRouter } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Button } from '@/components/ui/Button';
import { EmptyState } from '@/components/ui/StateViews';
import { theme } from '@/constants/theme';
import { confirmAction } from '@/lib/confirm';
import { formatDate, formatKRW } from '@/lib/format';
import { useI18n } from '@/lib/i18n';
import { mapsUrl } from '@/lib/maps';
import { useStores } from '@/lib/queries';
import { useShoppingListStore } from '@/store/shoppingListStore';

export default function ShoppingListScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const { t, language } = useI18n();
  const list = useShoppingListStore((s) => s.lists.find((l) => l.id === id));
  const remove = useShoppingListStore((s) => s.remove);
  const stores = useStores();

  if (!list) return <EmptyState icon="list-outline" title={t('common.notFound')} />;
  const store = stores.data?.find((s) => s.id === list.storeId);

  return (
    <SafeAreaView style={styles.screen} edges={['bottom']}>
      <ScrollView contentContainerStyle={styles.content}>
        <View style={styles.banner}>
          <Ionicons name="storefront-outline" size={20} color={theme.colors.white} />
          <Text style={styles.bannerText}>{t('list.showStaff')}</Text>
        </View>

        <View style={styles.card}>
          <Text style={styles.staffMessage}>
            {t('list.staffMessage')}
          </Text>
          {list.lines.map((line) => (
            <View key={`${line.productId}-${line.shadeId ?? ''}`} style={styles.line}>
              <View style={{ flex: 1 }}>
                <Text style={styles.brand}>{line.brand}</Text>
                <Text style={styles.nameKo}>
                  {line.nameKo}
                </Text>
                {line.shadeName ? <Text style={styles.shade}>{t('list.shadeLabel')} {line.shadeName}</Text> : null}
                <Text style={styles.nameEn}>{line.name}</Text>
              </View>
              <View style={styles.qtyBox}>
                <Text style={styles.qtyLabel}>{t('list.qty')}</Text>
                <Text style={styles.qty}>{line.quantity}</Text>
              </View>
            </View>
          ))}
          <View style={styles.totalRow}>
            <Text style={styles.totalLabel}>{t('list.total')}</Text>
            <Text style={styles.totalValue}>{formatKRW(list.totalKRW)}</Text>
          </View>
        </View>

        <Text style={styles.meta}>{formatDate(list.createdAt, language)}</Text>
        {store ? (
          <View style={styles.storeRow}>
            <Text style={styles.meta}>
              {t('list.store')}: {store.name}
            </Text>
            <Button
              label={t('checkout.openMap')}
              icon="map-outline"
              variant="secondary"
              compact
              onPress={() => WebBrowser.openBrowserAsync(mapsUrl(store))}
            />
          </View>
        ) : null}

        <Button
          label={t('common.delete')}
          variant="ghost"
          compact
          style={{ marginTop: 24 }}
          onPress={() =>
            confirmAction(t('list.deleteConfirm'), t('common.delete'), t('common.cancel'), () => {
              remove(list.id);
              router.back();
            })
          }
        />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  content: { padding: theme.spacing.lg, paddingBottom: 40 },
  banner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    backgroundColor: theme.colors.ink,
    padding: 14,
    borderRadius: theme.radius.md,
    marginBottom: 12,
  },
  bannerText: { flex: 1, color: theme.colors.white, fontSize: theme.font.small, fontWeight: '600' },
  card: { backgroundColor: theme.colors.card, borderRadius: theme.radius.lg, padding: 18, ...theme.shadow },
  staffMessage: { fontSize: theme.font.title, fontWeight: '800', color: theme.colors.ink, marginBottom: 8 },
  line: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingVertical: 14,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: theme.colors.border,
  },
  brand: { fontSize: theme.font.title, fontWeight: '800', color: theme.colors.accent },
  nameKo: { fontSize: 22, fontWeight: '800', color: theme.colors.ink, lineHeight: 30 },
  shade: { fontSize: theme.font.title, fontWeight: '800', color: theme.colors.rose, marginTop: 4 },
  nameEn: { fontSize: 12, color: theme.colors.inkMuted, marginTop: 4 },
  qtyBox: { alignItems: 'center', minWidth: 56 },
  qtyLabel: { fontSize: 12, color: theme.colors.inkMuted },
  qty: { fontSize: 30, fontWeight: '800', color: theme.colors.ink },
  totalRow: { flexDirection: 'row', justifyContent: 'space-between', marginTop: 14 },
  totalLabel: { fontSize: theme.font.body, color: theme.colors.inkMuted },
  totalValue: { fontSize: theme.font.title, fontWeight: '800', color: theme.colors.ink },
  meta: { fontSize: 12, color: theme.colors.inkMuted, marginTop: 14 },
  storeRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
});
