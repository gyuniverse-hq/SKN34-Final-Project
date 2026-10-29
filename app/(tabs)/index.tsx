import { KStyleCollection, type KStyleCollectionTab } from '@/components/celeb/KStyleCollection';
import { HomeChatButton } from '@/components/chat/HomeChatButton';
import { ProductCard } from '@/components/shop/ProductCard';
import { ShopHeaderActions } from '@/components/shop/ShopHeaderActions';
import { SkinMatchSection } from '@/components/skin/SkinMatchSection';
import { InlineState } from '@/components/ui/InlineState';
import { SectionHeader } from '@/components/ui/SectionHeader';
import { theme } from '@/constants/theme';
import { CELEBRITIES } from '@/constants/celebrities';
import { useSkinMatchedProducts } from '@/hooks/useSkinMatchedProducts';
import { useI18n } from '@/lib/i18n';
import { useLooks, useProducts } from '@/lib/queries';
import { celebrityHref, lookHref, productHref } from '@/lib/routes';
import Ionicons from '@expo/vector-icons/Ionicons';
import { useRouter, type Href } from 'expo-router';
import { useState } from 'react';
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

const HOME_PRODUCT_LIMIT = 8;
const HOME_LOOK_LIMIT = 4;
const SKIN_TYPE_CONCERN_LIMIT = 2;

export default function HomeScreen() {
  const router = useRouter();
  const { t } = useI18n();
  const [collectionTab, setCollectionTab] = useState<KStyleCollectionTab>('celebrity');
  const looks = useLooks();
  const products = useProducts();
  const skinMatch = useSkinMatchedProducts();
  const skinTypeLabel = skinMatch.concerns
    .slice(0, SKIN_TYPE_CONCERN_LIMIT)
    .map((c) => t(`concern.${c}`))
    .join('·');

  const refreshing = looks.isRefetching || products.isRefetching || skinMatch.products.isRefetching;
  const refresh = () => {
    looks.refetch();
    products.refetch();
    skinMatch.products.refetch();
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
          <View style={styles.headerActions}>
            <Pressable accessibilityRole="button" accessibilityLabel={t('search.title')} onPress={() => router.push('/discover' as Href)} style={styles.searchButton}>
              <Ionicons name="search-outline" size={22} color={theme.colors.ink} />
            </Pressable>
            <ShopHeaderActions onOpenCart={() => router.push('/cart')} />
          </View>
        </View>

        <KStyleCollection
          activeTab={collectionTab}
          celebrities={CELEBRITIES.map((celebrity) => ({ celebrity, name: t(celebrity.nameKey) }))}
          looks={looks.data?.slice(0, HOME_LOOK_LIMIT)}
          looksLoading={looks.isPending}
          looksError={looks.isError}
          eyebrow={t('home.eyebrow')}
          title={t('home.collectionTitle')}
          celebrityLabel={t('home.collectionCelebrity')}
          styleLabel={t('home.collectionStyle')}
          viewAllLabel={t('home.viewAll')}
          emptyMessage={collectionTab === 'celebrity' ? t('home.collectionCelebrityEmpty') : t('looks.empty')}
          onTabChange={setCollectionTab}
          onViewAll={() => router.push(collectionTab === 'celebrity' ? '/celebrities' as Href : '/celeb')}
          onRetry={() => looks.refetch()}
          onPressCelebrity={(celebrity) => router.push(celebrityHref(celebrity.id))}
          onPressStyle={(look) => router.push(lookHref(look.id))}
        />

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

        <SkinMatchSection
          title={skinTypeLabel ? t('home.skinMatchTitle', { type: skinTypeLabel }) : t('home.skinMatchIntro')}
          actionLabel={skinMatch.hasProfile ? t('home.skinReanalyze') : t('home.skin')}
          products={skinMatch.products.data?.slice(0, HOME_PRODUCT_LIMIT)}
          loading={skinMatch.products.isPending}
          error={skinMatch.products.isError}
          emptyMessage={t('home.skinMatchEmpty')}
          onAction={() => router.push('/skin-consent')}
          onRetry={() => skinMatch.products.refetch()}
          onPressProduct={(p) => router.push(productHref(p.id))}
        />

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
  headerActions: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  searchButton: { width: 40, height: 40, borderRadius: theme.radius.pill, borderWidth: 1, borderColor: theme.colors.border, backgroundColor: theme.colors.card, alignItems: 'center', justifyContent: 'center' },
  section: { marginTop: 28 },
  productRail: { marginHorizontal: -6 },
  productItem: { width: 168 },
  disclaimer: { marginTop: 28, fontSize: 11, lineHeight: 16, color: theme.colors.inkFaint },
});
