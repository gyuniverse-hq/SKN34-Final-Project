import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useCallback, useState } from 'react';
import { FlatList, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ProductCard } from '@/components/shop/ProductCard';
import { SearchBar } from '@/components/shop/SearchBar';
import { Button } from '@/components/ui/Button';
import { Chip } from '@/components/ui/Chip';
import { Notice } from '@/components/ui/Notice';
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/StateViews';
import { theme } from '@/constants/theme';
import { useDebouncedValue } from '@/hooks/useDebouncedValue';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import { useProducts } from '@/lib/queries';
import {
  parseCategory,
  parseConcerns,
  paramValue,
  parseSearchSource,
  PRODUCT_CATEGORIES,
  productHref,
} from '@/lib/routes';
import type { Product, ProductCategory, SkinConcern } from '@/types';

/** Search results for home search and skin-analysis filters (`q`, `category`, `concerns`, `source`). */
export default function SearchScreen() {
  const params = useLocalSearchParams<{ q?: string; category?: string; concerns?: string; source?: string }>();
  const router = useRouter();
  const { t } = useI18n();
  const source = parseSearchSource(params.source);
  const [query, setQuery] = useState(paramValue(params.q) ?? '');
  const [category, setCategory] = useState<ProductCategory | undefined>(parseCategory(params.category));
  const [concerns, setConcerns] = useState<SkinConcern[]>(parseConcerns(params.concerns));
  const debouncedQuery = useDebouncedValue(query.trim(), 300);
  const products = useProducts({ q: debouncedQuery || undefined, category, concerns });

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
    <View style={styles.header}>
      <SearchBar value={query} onChangeText={setQuery} placeholder={t('shop.searchPlaceholder')} />
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
      {concerns.length > 0 ? (
        <View style={styles.filters}>
          <Text style={styles.filtersLabel}>{t('search.concernFilters')}</Text>
          <View style={styles.filterChips}>
            {concerns.map((c) => (
              <Chip
                key={c}
                label={`${t(`concern.${c}` as TranslationKey)} ×`}
                selected
                onPress={() => setConcerns(concerns.filter((x) => x !== c))}
              />
            ))}
          </View>
        </View>
      ) : null}
      {source === 'skin' ? (
        <Notice body={t('search.skinNotice')}>
          <Button label={t('search.editFilters')} variant="ghost" compact onPress={() => router.back()} style={styles.noticeBtn} />
        </Notice>
      ) : null}
      {!products.isPending && !products.isError && products.data.length > 0 ? (
        <Text style={styles.count}>{t('search.count', { count: products.data.length })}</Text>
      ) : null}
    </View>
  );

  const filtered = !!debouncedQuery || !!category || concerns.length > 0;

  return (
    <SafeAreaView style={styles.screen} edges={['bottom']}>
      <Stack.Screen options={{ title: t(source === 'skin' ? 'search.skinTitle' : 'search.title') }} />
      <FlatList
        data={products.data ?? []}
        keyExtractor={(item) => item.id}
        numColumns={2}
        renderItem={renderItem}
        ListHeaderComponent={header}
        contentContainerStyle={styles.list}
        keyboardShouldPersistTaps="handled"
        keyboardDismissMode="on-drag"
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
              action={
                filtered ? (
                  <Button
                    label={t('search.clearFilters')}
                    variant="secondary"
                    onPress={() => {
                      setQuery('');
                      setCategory(undefined);
                      setConcerns([]);
                    }}
                  />
                ) : undefined
              }
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
  header: { gap: 10, paddingHorizontal: 6, paddingTop: 12 },
  chips: { gap: 8 },
  filters: { gap: 6 },
  filtersLabel: { fontSize: 12, fontWeight: '700', color: theme.colors.inkMuted },
  filterChips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  noticeBtn: { alignSelf: 'flex-start', paddingHorizontal: 0 },
  count: { fontSize: 12, fontWeight: '700', color: theme.colors.inkMuted, marginTop: 4 },
});
