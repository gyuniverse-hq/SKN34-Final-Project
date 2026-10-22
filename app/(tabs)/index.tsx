import { useRouter } from 'expo-router';
import { useCallback, useState } from 'react';
import Ionicons from '@expo/vector-icons/Ionicons';
import { FlatList, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { LookCard } from '@/components/celeb/LookCard';
import { ProductCard } from '@/components/shop/ProductCard';
import { SearchBar } from '@/components/shop/SearchBar';
import { ShopHeaderActions } from '@/components/shop/ShopHeaderActions';
import { Chip } from '@/components/ui/Chip';
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/StateViews';
import { theme } from '@/constants/theme';
import { useDebouncedValue } from '@/hooks/useDebouncedValue';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import { useLooks, useProducts } from '@/lib/queries';
import type { Product, ProductCategory } from '@/types';

const CATEGORIES: ProductCategory[] = ['lip', 'cheek', 'eye', 'base', 'skincare', 'suncare'];

export default function ShopScreen() {
  const router = useRouter();
  const { t } = useI18n();
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState<ProductCategory | undefined>();
  const debouncedQuery = useDebouncedValue(query.trim(), 300);

  const products = useProducts({ q: debouncedQuery || undefined, category });
  const looks = useLooks();
  const showLooks = !debouncedQuery && !category;

  const renderItem = useCallback(
    ({ item }: { item: Product }) => (
      <ProductCard
        product={item}
        shadeLabel={t('shop.shadeCount', { count: item.shades.length })}
        onPress={() => router.push(`/product/${item.id}`)}
      />
    ),
    [router, t]
  );

  const header = (
    <View>
      <View style={styles.hero}>
        <View style={styles.heroText}>
          <Text style={styles.brand} accessibilityRole="header">
            {t('shop.title')}
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
        {CATEGORIES.map((c) => (
          <Chip
            key={c}
            label={t(`shop.cat.${c}` as TranslationKey)}
            selected={category === c}
            onPress={() => setCategory(category === c ? undefined : c)}
          />
        ))}
      </ScrollView>

      <Pressable
        onPress={() => router.push('/ingredients')}
        accessibilityRole="button"
        style={({ pressed }) => [styles.ingredientsLink, pressed && { opacity: 0.85 }]}>
        <Ionicons name="flask-outline" size={18} color={theme.colors.rose} />
        <Text style={styles.ingredientsText}>{t('shop.ingredientsLink')}</Text>
        <Ionicons name="chevron-forward" size={16} color={theme.colors.inkFaint} />
      </Pressable>

      {showLooks && looks.data?.length ? (
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>{t('shop.featuredLooks')}</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.looks}>
            {looks.data.map((look) => (
              <LookCard
                key={look.id}
                look={look}
                width={240}
                subtitle={t('looks.itemCount', { count: look.items.length })}
                onPress={() => router.push(`/look/${look.id}`)}
              />
            ))}
          </ScrollView>
        </View>
      ) : null}

      <Text style={[styles.sectionTitle, styles.productsTitle]}>{t('shop.products')}</Text>
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
          <RefreshControl
            refreshing={products.isRefetching}
            onRefresh={() => {
              products.refetch();
              looks.refetch();
            }}
            tintColor={theme.colors.rose}
          />
        }
        ListEmptyComponent={
          products.isPending ? (
            <LoadingState />
          ) : products.isError ? (
            <ErrorState error={products.error} onRetry={() => products.refetch()} />
          ) : (
            <EmptyState
              icon={debouncedQuery || category ? 'search-outline' : 'cube-outline'}
              title={debouncedQuery || category ? t('shop.noResults') : t('shop.emptyCatalog')}
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
  hero: { flexDirection: 'row', alignItems: 'flex-start', gap: 12, paddingHorizontal: 10, paddingTop: 12 },
  heroText: { flex: 1 },
  brand: { fontSize: theme.font.h1, fontWeight: '800', color: theme.colors.ink, letterSpacing: -0.5 },
  tagline: { fontSize: theme.font.small, color: theme.colors.inkMuted, marginTop: 2 },
  search: { paddingHorizontal: 6, paddingTop: 14, paddingBottom: 10 },
  chips: { gap: 8, paddingHorizontal: 6, paddingBottom: 6 },
  section: { marginTop: 18 },
  sectionTitle: {
    fontSize: theme.font.title,
    fontWeight: '800',
    color: theme.colors.ink,
    paddingHorizontal: 6,
    marginBottom: 10,
  },
  productsTitle: { marginTop: 22, marginBottom: 4 },
  looks: { gap: 12, paddingHorizontal: 6 },
  ingredientsLink: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginHorizontal: 6,
    marginTop: 10,
    padding: 12,
    borderRadius: theme.radius.md,
    backgroundColor: theme.colors.roseSoft,
  },
  ingredientsText: { flex: 1, fontSize: theme.font.small, fontWeight: '700', color: theme.colors.roseDark },
});
