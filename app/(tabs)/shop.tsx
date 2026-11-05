import Ionicons from '@expo/vector-icons/Ionicons';
import { useRouter } from 'expo-router';
import { useCallback, useState } from 'react';
import { FlatList, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ProductCard } from '@/components/shop/ProductCard';
import { SearchBar } from '@/components/shop/SearchBar';
import { ShopHeaderActions } from '@/components/shop/ShopHeaderActions';
import { Chip } from '@/components/ui/Chip';
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
          <Text style={styles.tagline}>{t('shop.tagline')}</Text>
        </View>
        <ShopHeaderActions onOpenCart={() => router.push('/cart')} />
      </View>
      <View style={styles.search}>
        <SearchBar value={query} onChangeText={setQuery} placeholder={t('shop.searchPlaceholder')} />
      </View>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chips}>
        <Chip label={t('shop.all')} selected={!category} onPress={() => setCategory(undefined)} />
        {PRODUCT_CATEGORIES.map((c) => (
          <Chip
            key={c}
            label={t(`shop.cat.${c}` as TranslationKey)}
            selected={category === c}
            onPress={() => setCategory(category === c ? undefined : c)}
          />
        ))}
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
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  list: { paddingHorizontal: 10, paddingBottom: 32 },
  hero: { flexDirection: 'row', alignItems: 'flex-start', gap: 12, paddingHorizontal: 6, paddingTop: 12 },
  heroText: { flex: 1 },
  title: { fontSize: theme.font.h1, fontWeight: '800', color: theme.colors.ink, letterSpacing: -0.5 },
  tagline: { fontSize: theme.font.small, color: theme.colors.inkMuted, marginTop: 2 },
  search: { paddingHorizontal: 6, paddingTop: 14, paddingBottom: 10 },
  chips: { gap: 8, paddingHorizontal: 6, paddingBottom: 6 },
  links: { gap: 8, marginTop: 10, marginHorizontal: 6 },
  link: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    minHeight: theme.hitTarget,
    paddingHorizontal: 12,
    borderRadius: theme.radius.md,
    backgroundColor: theme.colors.roseSoft,
  },
  linkText: { flex: 1, fontSize: theme.font.small, fontWeight: '700', color: theme.colors.roseDark },
  count: { marginTop: 16, marginHorizontal: 6, fontSize: 12, fontWeight: '700', color: theme.colors.inkMuted },
});
