import { useLocalSearchParams, useRouter } from 'expo-router';
import { useMemo, useState } from 'react';
import { Pressable, SectionList, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { SearchBar } from '@/components/shop/SearchBar';
import { InlineState } from '@/components/ui/InlineState';
import { ProductImage } from '@/components/ui/ProductImage';
import { theme } from '@/constants/theme';
import { inRankingCategory, rankedProducts, type RankingCategory } from '@/lib/discovery';
import { formatKRW } from '@/lib/format';
import { useI18n } from '@/lib/i18n';
import { useProducts } from '@/lib/queries';
import { productHref, searchHref } from '@/lib/routes';
import { useRecentSearchStore } from '@/store/recentSearchStore';
import type { Product } from '@/types';

interface ProductRow { product: Product; rank?: number }

export default function RankingsScreen() {
  const { category: initial } = useLocalSearchParams<{ category?: string }>();
  const router = useRouter();
  const { t } = useI18n();
  const [category, setCategory] = useState<RankingCategory>(initial === 'skincare' ? 'skincare' : 'makeup');
  const [query, setQuery] = useState('');
  const addSearch = useRecentSearchStore((s) => s.add);
  const products = useProducts();
  const { ranked, others } = useMemo(() => {
    const all = products.data ?? [];
    const rankedItems = rankedProducts(all, category);
    const rankedIds = new Set(rankedItems.map(({ product }) => product.id));
    return { ranked: rankedItems, others: all.filter((product) => inRankingCategory(product, category) && !rankedIds.has(product.id)).map((product) => ({ product })) };
  }, [category, products.data]);
  const sections = [
    { title: t('discovery.ranking'), data: ranked as ProductRow[] },
    { title: t('discovery.otherProducts'), data: others as ProductRow[] },
  ];
  const submit = () => {
    const term = query.trim();
    if (!term) return;
    addSearch(term);
    router.push(searchHref({ q: term, source: 'home' }));
  };
  return (
    <SafeAreaView style={styles.screen} edges={['bottom']}>
      <SectionList sections={sections} keyExtractor={(item) => item.product.id} stickySectionHeadersEnabled={false}
        keyboardShouldPersistTaps="handled" contentContainerStyle={styles.content}
        ListHeaderComponent={<View>
          <SearchBar value={query} onChangeText={setQuery} placeholder={t('shop.searchPlaceholder')} onSubmit={submit} />
          <View style={styles.tabs} accessibilityRole="tablist">
            {(['makeup', 'skincare'] as const).map((tab) => (
              <Pressable key={tab} accessibilityRole="tab" accessibilityState={{ selected: tab === category }}
                onPress={() => setCategory(tab)} style={[styles.tab, category === tab && styles.tabActive]}>
                <Text style={[styles.tabText, category === tab && styles.tabTextActive]}>{t(tab === 'makeup' ? 'discovery.makeupRanking' : 'discovery.skinRanking')}</Text>
              </Pressable>
            ))}
          </View>
          <Text style={styles.note}>{t('discovery.rankingBasis')}</Text>
          {products.isPending ? <InlineState status="loading" /> : products.isError ? <InlineState status="error" onRetry={() => products.refetch()} /> : null}
          {!products.isPending && !products.isError && ranked.length === 0 ? <InlineState status="empty" message={t('discovery.rankingEmpty')} /> : null}
          {!products.isPending && !products.isError && ranked.length === 0 && others.length === 0 ? <Text style={styles.emptyCatalog}>{t('shop.emptyCatalog')}</Text> : null}
        </View>}
        renderSectionHeader={({ section }) => section.data.length ? <Text accessibilityRole="header" style={styles.sectionTitle}>{section.title}</Text> : null}
        renderItem={({ item }) => (
          <Pressable accessibilityRole="button" accessibilityLabel={`${item.product.brand} ${item.product.name}`}
            onPress={() => router.push(productHref(item.product.id))} style={({ pressed }) => [styles.row, pressed && styles.pressed]}>
            <View style={styles.rankCell}>{item.rank !== undefined ? <Text style={styles.rank}>{item.rank}</Text> : null}</View>
            <ProductImage uri={item.product.imageUrl} category={item.product.category} compact recyclingKey={item.product.id} style={styles.image} />
            <View style={styles.productBody}>
              <Text style={styles.brand} numberOfLines={1}>{item.product.brand}</Text>
              <Text style={styles.name} numberOfLines={2}>{item.product.name}</Text>
              <Text style={styles.price}>{formatKRW(item.product.priceKRW)}</Text>
            </View>
          </Pressable>
        )} />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  content: { padding: theme.spacing.lg, paddingBottom: 32 },
  tabs: { flexDirection: 'row', marginTop: 20, borderBottomWidth: 1, borderColor: theme.colors.border },
  tab: { flex: 1, alignItems: 'center', justifyContent: 'center', minHeight: 52, borderBottomWidth: 3, borderColor: 'transparent' },
  tabActive: { borderBottomColor: theme.colors.rose },
  tabText: { color: theme.colors.inkMuted, fontWeight: '700', fontSize: 15 },
  tabTextActive: { color: theme.colors.roseDark },
  note: { color: theme.colors.inkMuted, fontSize: 12, lineHeight: 18, marginVertical: 14 },
  sectionTitle: { color: theme.colors.ink, fontWeight: '800', fontSize: 16, marginTop: 22, marginBottom: 4 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 12, borderBottomWidth: 1, borderColor: theme.colors.border, minHeight: 104 },
  rankCell: { width: 28, alignItems: 'center' },
  rank: { color: theme.colors.rose, fontSize: 18, fontWeight: '800' },
  image: { width: 74, height: 74, borderRadius: theme.radius.sm, backgroundColor: theme.colors.surfaceAlt },
  productBody: { flex: 1, gap: 3 },
  brand: { color: theme.colors.inkMuted, fontSize: 12 },
  name: { color: theme.colors.ink, fontSize: 15, lineHeight: 20, fontWeight: '700' },
  price: { color: theme.colors.ink, fontSize: 13, fontWeight: '600' },
  emptyCatalog: { color: theme.colors.inkMuted, textAlign: 'center', marginTop: 18 },
  pressed: { opacity: 0.8 },
});
