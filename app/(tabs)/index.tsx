import { useRouter, type Href } from 'expo-router';
import { useMemo } from 'react';
import { RefreshControl, ScrollView, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { KStyleCollection } from '@/components/celeb/KStyleCollection';
import { HomeCategories, HomeProductSection } from '@/components/home/HomeCatalog';
import { HomeSearch } from '@/components/home/HomeSearch';
import { ShopHeaderActions } from '@/components/shop/ShopHeaderActions';
import { SkinMatchSection } from '@/components/skin/SkinMatchSection';
import { InlineState } from '@/components/ui/InlineState';
import { homeLayout, homeType } from '@/constants/homeLayout';
import { theme } from '@/constants/theme';
import { useSkinMatchedProducts } from '@/hooks/useSkinMatchedProducts';
import { rankedProducts, type RankingCategory } from '@/lib/discovery';
import { useI18n } from '@/lib/i18n';
import { useProducts, useStyleLooks } from '@/lib/queries';
import { celebrityHref, productHref, searchHref } from '@/lib/routes';
import type { Product } from '@/types';

export default function HomeScreen() {
  const router = useRouter();
  const { t } = useI18n();
  const width = Math.min(useWindowDimensions().width, homeLayout.maxWidth);
  const looks = useStyleLooks();
  const products = useProducts();
  const skinMatch = useSkinMatchedProducts();
  const shelves = useMemo(() => {
    const all = products.data ?? [];
    return {
      hot: all.filter(p => p.tags.includes('bestseller')),
      makeup: rankedProducts(all, 'makeup').map(entry => entry.product),
      skincare: rankedProducts(all, 'skincare').map(entry => entry.product),
      newArrivals: all.filter(p => p.tags.includes('new')),
      all,
    };
  }, [products.data]);
  const skinTypeLabel = skinMatch.concerns.slice(0, 2).map(c => t(`concern.${c}`)).join('·');
  const refresh = () => {
    void looks.refetch();
    void products.refetch();
    if (skinMatch.visible) void skinMatch.products.refetch();
  };
  const openProduct = (product: Product) => router.push(productHref(product.id));
  const openChart = (category: RankingCategory) => router.push({ pathname: '/rankings', params: { category } } as Href);

  return (
    <SafeAreaView style={styles.screen} edges={['top']}>
      <ScrollView contentContainerStyle={[styles.content, { width }]} keyboardShouldPersistTaps="handled" keyboardDismissMode="on-drag"
        showsVerticalScrollIndicator={false}
        refreshControl={<RefreshControl refreshing={looks.isRefetching || products.isRefetching || skinMatch.products.isRefetching}
          onRefresh={refresh} tintColor={theme.colors.rose} />}>
        <View style={styles.header}>
          <Text style={styles.logo} accessibilityRole="header">VISHUE<Text style={styles.logoDot}>.</Text></Text>
          <ShopHeaderActions showLanguage={false} onOpenCart={() => router.push('/cart')} />
        </View>
        <HomeSearch onSearch={q => router.push(searchHref({ q, source: 'home' }))}>
          <KStyleCollection pageWidth={width} looks={looks.data} looksLoading={looks.isPending} looksError={looks.isError}
            onRetry={() => void looks.refetch()} onViewAll={tab => router.push(tab === 'celebrity' ? '/celebrities' : '/celeb')}
            onPressCelebrity={id => router.push(celebrityHref(id))}
            onPressStyle={look => router.push({ pathname: '/style-look/[id]', params: { id: look.id } } as Href)} />
          <HomeCategories onPress={category => router.push(searchHref({ category, source: 'home' }))} />
          {products.isPending || products.isError ? (
            <View style={styles.catalogState}><InlineState status={products.isPending ? 'loading' : 'error'} onRetry={() => void products.refetch()} /></View>
          ) : (
            <>
              <HomeProductSection featured pageWidth={width} title={t('discovery.hot')} products={shelves.hot}
                emptyMessage={t('discovery.hotEmpty')} onPress={openProduct} />
              <HomeProductSection preview="makeup" pageWidth={width} title={t('discovery.makeupRanking')} products={shelves.makeup}
                emptyMessage={t('discovery.rankingEmpty')} onViewAll={() => openChart('makeup')} onPress={openProduct} />
              <HomeProductSection preview="skincare" pageWidth={width} title={t('discovery.skinRanking')} products={shelves.skincare}
                emptyMessage={t('discovery.rankingEmpty')} onViewAll={() => openChart('skincare')} onPress={openProduct} />
              <HomeProductSection preview="new" pageWidth={width} title={t('discovery.new')} products={shelves.newArrivals}
                emptyMessage={t('discovery.newEmpty')} onViewAll={() => router.push(searchHref({ collection: 'new', source: 'home' }))} onPress={openProduct} />
              <HomeProductSection pageWidth={width} title={t('home.pickTitle')} products={shelves.all}
                emptyMessage={t('shop.emptyCatalog')} onViewAll={() => router.push('/shop')} onPress={openProduct} />
            </>
          )}
          <SkinMatchSection
            title={skinMatch.visible && skinTypeLabel ? t('home.skinMatchTitle', { type: skinTypeLabel }) : t('skinAccess.homeTitle')}
            actionLabel={skinMatch.checking || skinMatch.failed ? undefined :
              t(skinMatch.visible ? 'home.skinReanalyze' : skinMatch.needsSubscription ? 'skinAccess.viewMembership' : 'skinAccess.analyze')}
            availability={skinMatch.visible ? undefined : t(skinMatch.needsSubscription ? 'skinAccess.afterJoin' : 'skinAccess.afterAnalysis')}
            products={skinMatch.products.data?.slice(0, 8)}
            loading={skinMatch.checking || (skinMatch.visible && skinMatch.products.isPending)}
            error={skinMatch.failed || (skinMatch.visible && skinMatch.products.isError)}
            emptyMessage={t('home.skinMatchEmpty')}
            onAction={() => router.push(skinMatch.needsSubscription ? '/membership' : '/skin-consent')}
            onRetry={() => skinMatch.failed ? skinMatch.retry() : skinMatch.products.refetch()}
            onPressProduct={openProduct} />
          <Text style={styles.disclaimer}>{t('home.disclaimer')}</Text>
        </HomeSearch>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: homeLayout.background },
  content: { alignSelf: 'center', paddingBottom: 96 },
  header: { paddingHorizontal: 17, minHeight: homeLayout.headerHeight, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  logo: { ...homeType(34), fontFamily: homeLayout.displayFont, color: theme.colors.roseDark },
  logoDot: { color: theme.colors.accent },
  catalogState: { marginHorizontal: homeLayout.gutter, marginBottom: 23 },
  disclaimer: { ...homeType(11), marginHorizontal: homeLayout.gutter, marginTop: 18, lineHeight: 16, color: theme.colors.inkFaint },
});
