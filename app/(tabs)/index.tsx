import { KStyleCollection, type KStyleCollectionTab } from '@/components/celeb/KStyleCollection';
import { HomeChatButton } from '@/components/chat/HomeChatButton';
import { ProductCard } from '@/components/shop/ProductCard';
import { SearchBar } from '@/components/shop/SearchBar';
import { ShopHeaderActions } from '@/components/shop/ShopHeaderActions';
import { ActionTile } from '@/components/ui/ActionTile';
import { InlineState } from '@/components/ui/InlineState';
import { SectionHeader } from '@/components/ui/SectionHeader';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';
import { displayableIdolLooks } from '@/lib/idolLooks';
import { useIdolLooks, useLooks, useProducts } from '@/lib/queries';
import { idolLookHref, lookHref, productHref, searchHref } from '@/lib/routes';
import { useRouter } from 'expo-router';
import { useState } from 'react';
import { RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

const HOME_PRODUCT_LIMIT = 8;

export default function HomeScreen() {
  const router = useRouter();
  const { t } = useI18n();
  const [query, setQuery] = useState('');
  const [collectionTab, setCollectionTab] = useState<KStyleCollectionTab>('celebrity');
  const idolLooks = useIdolLooks();
  const looks = useLooks();
  const products = useProducts();
  const featuredIdolLooks = displayableIdolLooks(idolLooks.data);

  const submitSearch = () => {
    const q = query.trim();
    if (q) router.push(searchHref({ q, source: 'home' }));
  };

  const refreshing = idolLooks.isRefetching || looks.isRefetching || products.isRefetching;
  const refresh = () => {
    idolLooks.refetch();
    looks.refetch();
    products.refetch();
  };

  return (
    <SafeAreaView style={styles.screen} edges={['top']}>
      <ScrollView
        contentContainerStyle={styles.content}
        keyboardShouldPersistTaps="handled"
        keyboardDismissMode="on-drag"
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={theme.colors.rose} />}>
        <View style={styles.header}>
          <Text style={styles.logo} accessibilityRole="header">
            VISHUE<Text style={styles.logoDot}>.</Text>
          </Text>
          <ShopHeaderActions onOpenCart={() => router.push('/cart')} />
        </View>

        <KStyleCollection
          activeTab={collectionTab}
          idolLooks={featuredIdolLooks}
          looks={looks.data}
          idolLoading={idolLooks.isPending}
          looksLoading={looks.isPending}
          idolError={idolLooks.isError}
          looksError={looks.isError}
          eyebrow={t('home.eyebrow')}
          title={t('home.collectionTitle')}
          celebrityLabel={t('home.collectionCelebrity')}
          styleLabel={t('home.collectionStyle')}
          viewAllLabel={t('home.viewAll')}
          emptyMessage={collectionTab === 'celebrity' ? t('home.collectionCelebrityEmpty') : t('looks.empty')}
          onTabChange={setCollectionTab}
          onViewAll={() => router.push(collectionTab === 'celebrity' ? '/idol-looks' : '/celeb')}
          onRetry={() => (collectionTab === 'celebrity' ? idolLooks.refetch() : looks.refetch())}
          onPressIdol={(look) => router.push(idolLookHref(look.id))}
          onPressStyle={(look) => router.push(lookHref(look.id))}
        />

        <View style={styles.search}>
          <SearchBar value={query} onChangeText={setQuery} onSubmit={submitSearch} placeholder={t('home.searchPlaceholder')} />
        </View>

        <View style={styles.tiles}>
          <ActionTile icon="sparkles-outline" title={t('home.looks')} body={t('home.looksBody')} onPress={() => router.push('/celeb')} />
          <ActionTile icon="scan-outline" title={t('home.ar')} body={t('home.arBody')} onPress={() => router.push('/ar')} />
          <ActionTile icon="search-outline" title={t('home.search')} body={t('home.searchBody')} onPress={() => router.push('/shop')} />
          <ActionTile icon="water-outline" title={t('home.skin')} body={t('home.skinBody')} onPress={() => router.push('/skin-consent')} />
        </View>

        <View style={styles.section}>
          <SectionHeader
            eyebrow={t('home.pickEyebrow')}
            title={t('home.pickTitle')}
            actionLabel={t('home.viewAll')}
            onAction={() => router.push('/shop')}
          />
          {products.isPending ? (
            <InlineState status="loading" />
          ) : products.isError ? (
            <InlineState status="error" onRetry={() => products.refetch()} />
          ) : products.data.length === 0 ? (
            <InlineState status="empty" message={t('shop.emptyCatalog')} />
          ) : (
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.productRail}>
              {products.data.slice(0, HOME_PRODUCT_LIMIT).map((p) => (
                <View key={p.id} style={styles.productItem}>
                  <ProductCard
                    product={p}
                    shadeLabel={t('shop.shadeCount', { count: p.shades.length })}
                    onPress={() => router.push(productHref(p.id))}
                  />
                </View>
              ))}
            </ScrollView>
          )}
        </View>

        <Text style={styles.disclaimer}>{t('home.disclaimer')}</Text>
      </ScrollView>
      <HomeChatButton label={t('home.chatFab')} hint={t('home.chatFabHint')} onPress={() => router.push('/chat')} />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  content: { padding: theme.spacing.lg, paddingBottom: 104 },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
  logo: { fontFamily: theme.fontFamily.display, fontSize: 28, fontWeight: '700', color: theme.colors.rose, letterSpacing: -0.5 },
  logoDot: { color: theme.colors.accent },
  search: { marginTop: 14 },
  tiles: { flexDirection: 'row', gap: 8, marginTop: 12 },
  section: { marginTop: 28 },
  productRail: { marginHorizontal: -6 },
  productItem: { width: 168 },
  disclaimer: { marginTop: 28, fontSize: 11, lineHeight: 16, color: theme.colors.inkFaint },
});
