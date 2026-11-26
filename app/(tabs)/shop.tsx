import Ionicons from '@expo/vector-icons/Ionicons';
import { useRouter } from 'expo-router';
import { useCallback, useState } from 'react';
import { FlatList, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ProductCard } from '@/components/ui/ProductCard';
import { SearchBar } from '@/components/shop/SearchBar';
import { ShopHeaderActions } from '@/components/shop/ShopHeaderActions';
import { homeLayout, homeType, tabTitle } from '@/constants/homeLayout';
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/StateViews';
import { theme } from '@/constants/theme';
import { useDebouncedValue } from '@/hooks/useDebouncedValue';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import { useProducts } from '@/lib/queries';
import { PRODUCT_CATEGORIES, productHref } from '@/lib/routes';
import { useCompareStore } from '@/store/compareStore';
import type { Product, ProductCategory } from '@/types';

export default function ShopScreen() {
  const router = useRouter();
  const { t } = useI18n();
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState<ProductCategory | undefined>();
  const debouncedQuery = useDebouncedValue(query.trim(), 300);
  const compareCount = useCompareStore((s) => s.items.length);
  const products = useProducts({ q: debouncedQuery || undefined, category });
  const filtered = !!debouncedQuery || !!category;

  const renderItem = useCallback(
    ({ item }: { item: Product }) => (
      <ProductCard
        product={item}
        shadeLabel={t('shop.shadeCount', { count: item.shades.length })}
        onPress={() => router.push(productHref(item.id))}
      />
    ),
    [router, t]
  );

  const header = (
    <View>
      <View style={styles.hero}>
        <View style={styles.heroText}>
          <Text style={styles.title} accessibilityRole="header">
            {t('shop.products')}
          </Text>
        </View>
        <ShopHeaderActions onOpenCart={() => router.push('/cart')} />
      </View>
      <View style={styles.search}>
        <SearchBar tonal value={query} onChangeText={setQuery} placeholder={t('shop.searchPlaceholder')} />
      </View>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chips}>
        {[undefined, ...PRODUCT_CATEGORIES].map((c) => {
          const selected = category === c;
          return (
            <Pressable key={c ?? 'all'} accessibilityRole="button" aria-selected={selected}
              style={[styles.category, selected && styles.activeCategory]} onPress={() => setCategory(selected ? undefined : c)}>
              <Text style={[styles.categoryText, selected && styles.activeText]}>{c ? t(`shop.cat.${c}` as TranslationKey) : t('shop.all')}</Text>
            </Pressable>
          );
        })}
      </ScrollView>

      <View style={styles.links}>
        <Pressable
          onPress={() => router.push('/ingredients')}
          accessibilityRole="button"
          style={({ pressed }) => [styles.link, pressed && { opacity: 0.85 }]}>
          <Ionicons name="flask-outline" size={18} color={theme.colors.rose} />
          <Text style={styles.linkText}>{t('shop.ingredientsLink')}</Text>
          <Ionicons name="chevron-forward" size={16} color={theme.colors.inkFaint} />
        </Pressable>
        {compareCount > 0 ? (
          <Pressable
            onPress={() => router.push('/compare')}
            accessibilityRole="button"
            style={({ pressed }) => [styles.link, pressed && { opacity: 0.85 }]}>
            <Ionicons name="git-compare-outline" size={18} color={theme.colors.rose} />
            <Text style={styles.linkText}>{t('compare.open', { count: compareCount })}</Text>
            <Ionicons name="chevron-forward" size={16} color={theme.colors.inkFaint} />
          </Pressable>
        ) : null}
      </View>
      {!products.isPending && !products.isError && products.data.length > 0 ? (
        <Text style={styles.count}>{t('search.count', { count: products.data.length })}</Text>
      ) : null}
    </View>
  );

  return (
    <SafeAreaView style={styles.screen} edges={['top']}>
      <FlatList
        style={styles.catalog}
        data={products.data ?? []}
        keyExtractor={(item) => item.id}
        numColumns={2}
        renderItem={renderItem}
        ListHeaderComponent={header}
        contentContainerStyle={styles.list}
        keyboardShouldPersistTaps="handled"
        keyboardDismissMode="on-drag"
        refreshControl={
          <RefreshControl refreshing={products.isRefetching} onRefresh={() => void products.refetch()} tintColor={theme.colors.rose} />
        }
        ListEmptyComponent={
          products.isPending ? (
            <LoadingState />
          ) : products.isError ? (
            <ErrorState error={products.error} onRetry={() => products.refetch()} />
          ) : (
            <EmptyState
              icon={filtered ? 'search-outline' : 'cube-outline'}
              title={filtered ? t('shop.noResults') : t('shop.emptyCatalog')}
              body={filtered ? t('search.noResultsBody') : t('shop.emptyCatalogBody')}
            />
          )
        }
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: homeLayout.background },
  catalog: { flex: 1, width: '100%', maxWidth: homeLayout.maxWidth, alignSelf: 'center' },
  list: { paddingHorizontal: homeLayout.gutter - homeLayout.productGap / 2, paddingBottom: 92 },
  hero: { minHeight: homeLayout.headerHeight, flexDirection: 'row', alignItems: 'center', gap: 12, marginHorizontal: homeLayout.productGap / 2 },
  heroText: { flex: 1 },
  title: tabTitle,
  search: { marginHorizontal: homeLayout.productGap / 2, marginBottom: 6 },
  chips: { gap: 16, paddingHorizontal: homeLayout.productGap / 2 },
  category: { minHeight: theme.hitTarget, justifyContent: 'center', borderBottomWidth: 2, borderColor: 'transparent' },
  activeCategory: { borderColor: theme.colors.rose },
  categoryText: { ...homeType(14), color: theme.colors.inkMuted },
  activeText: { fontWeight: '600', color: theme.colors.roseDark },
  links: { gap: 6, marginTop: 14, marginHorizontal: homeLayout.productGap / 2 },
  link: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    minHeight: theme.hitTarget,
    paddingHorizontal: 12,
    borderRadius: 10,
    backgroundColor: theme.colors.cream,
  },
  linkText: { ...homeType(13), flex: 1, fontWeight: '500', color: theme.colors.roseDark },
  count: { ...homeType(12), marginTop: 16, marginBottom: 8, marginHorizontal: homeLayout.productGap / 2, color: theme.colors.inkMuted },
});
