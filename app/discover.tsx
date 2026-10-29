import Ionicons from '@expo/vector-icons/Ionicons';
import { useRouter, type Href } from 'expo-router';
import { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ProductCard } from '@/components/shop/ProductCard';
import { SearchBar } from '@/components/shop/SearchBar';
import { InlineState } from '@/components/ui/InlineState';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';
import { useProducts } from '@/lib/queries';
import { productHref, searchHref } from '@/lib/routes';
import { useRecentSearchStore } from '@/store/recentSearchStore';
import type { Product } from '@/types';

export default function DiscoverScreen() {
  const router = useRouter();
  const { t } = useI18n();
  const [query, setQuery] = useState('');
  const [keywordTab, setKeywordTab] = useState<'trending' | 'recent'>('trending');
  const searches = useRecentSearchStore((s) => s.searches);
  const addSearch = useRecentSearchStore((s) => s.add);
  const removeSearch = useRecentSearchStore((s) => s.remove);
  const products = useProducts();

  const search = (value: string) => {
    const term = value.trim();
    if (!term) return;
    addSearch(term);
    router.push(searchHref({ q: term, source: 'home' }));
  };
  const openRankings = (category: 'makeup' | 'skincare') =>
    router.push({ pathname: '/rankings', params: { category } } as Href);
  const all = products.data ?? [];
  const hot = all.filter((p) => p.tags.includes('bestseller')).slice(0, 8);
  const recent = all.filter((p) => p.tags.includes('new')).slice(0, 8);

  const rail = (title: string, items: Product[], empty: string) => (
    <View style={styles.section}>
      <Text style={styles.sectionTitle} accessibilityRole="header">{title}</Text>
      {products.isPending ? <InlineState status="loading" /> : products.isError ? (
        <InlineState status="error" onRetry={() => products.refetch()} />
      ) : items.length === 0 ? <InlineState status="empty" message={empty} /> : (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.rail}>
          {items.map((product) => (
            <View key={product.id} style={styles.product}>
              <ProductCard product={product} shadeLabel={t('shop.shadeCount', { count: product.shades.length })}
                onPress={() => router.push(productHref(product.id))} />
            </View>
          ))}
        </ScrollView>
      )}
    </View>
  );

  return (
    <SafeAreaView style={styles.screen} edges={['bottom']}>
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled" keyboardDismissMode="on-drag">
        <SearchBar value={query} onChangeText={setQuery} placeholder={t('shop.searchPlaceholder')} onSubmit={() => search(query)} />

        <View style={styles.quick}>
          <View style={styles.quickIntro}>
            <Ionicons name="sparkles-outline" size={26} color={theme.colors.rose} />
            <Text style={styles.quickTitle}>{t('discovery.quickTitle')}</Text>
            <Text style={styles.quickBody}>{t('discovery.quickBody')}</Text>
          </View>
          <View style={styles.quickActions}>
            <Pressable style={styles.quickButton} accessibilityRole="button" onPress={() => router.push('/ar')}>
              <Ionicons name="scan-outline" size={20} color={theme.colors.white} /><Text style={styles.quickButtonText}>{t('discovery.tryAr')}</Text>
            </Pressable>
            <Pressable style={styles.quickButton} accessibilityRole="button" onPress={() => router.push('/skin-consent')}>
              <Ionicons name="water-outline" size={20} color={theme.colors.white} /><Text style={styles.quickButtonText}>{t('discovery.skin')}</Text>
            </Pressable>
          </View>
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionTitle} accessibilityRole="header">{t('discovery.keywords')}</Text>
          <View style={styles.keywordBox}>
            <View style={styles.tabs} accessibilityRole="tablist">
              {(['trending', 'recent'] as const).map((tab) => (
                <Pressable key={tab} accessibilityRole="tab" accessibilityState={{ selected: keywordTab === tab }}
                  onPress={() => setKeywordTab(tab)} style={[styles.tab, keywordTab === tab && styles.tabActive]}>
                  <Text style={[styles.tabText, keywordTab === tab && styles.tabTextActive]}>{t(tab === 'trending' ? 'discovery.trending' : 'discovery.recent')}</Text>
                </Pressable>
              ))}
            </View>
            {keywordTab === 'trending' ? <Text style={styles.emptyText}>{t('discovery.trendingEmpty')}</Text> : searches.length === 0 ? (
              <Text style={styles.emptyText}>{t('discovery.recentEmpty')}</Text>
            ) : <View style={styles.recentList}>{searches.map((item) => (
              <View key={item} style={styles.recentRow}>
                <Pressable onPress={() => search(item)} accessibilityRole="button" style={styles.recentTerm}><Text style={styles.recentText} numberOfLines={1}>{item}</Text></Pressable>
                <Pressable onPress={() => removeSearch(item)} accessibilityRole="button" accessibilityLabel={t('discovery.removeSearch', { query: item })} hitSlop={8}>
                  <Ionicons name="close" size={18} color={theme.colors.inkMuted} />
                </Pressable>
              </View>
            ))}</View>}
          </View>
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionTitle} accessibilityRole="header">{t('discovery.ranking')}</Text>
          <View style={styles.rankLinks}>
            <Pressable onPress={() => openRankings('makeup')} accessibilityRole="button" style={styles.rankLink}>
              <Text style={styles.rankIcon}>💄</Text><Text style={styles.rankText}>{t('discovery.makeupRanking')}</Text><Ionicons name="chevron-forward" size={18} color={theme.colors.rose} />
            </Pressable>
            <Pressable onPress={() => openRankings('skincare')} accessibilityRole="button" style={styles.rankLink}>
              <Text style={styles.rankIcon}>✨</Text><Text style={styles.rankText}>{t('discovery.skinRanking')}</Text><Ionicons name="chevron-forward" size={18} color={theme.colors.rose} />
            </Pressable>
          </View>
        </View>
        {rail(t('discovery.hot'), hot, t('discovery.hotEmpty'))}
        {rail(t('discovery.new'), recent, t('discovery.newEmpty'))}
        {rail(t('discovery.catalog'), all.slice(0, 8), t('shop.emptyCatalog'))}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  content: { padding: theme.spacing.lg, paddingBottom: 36 },
  quick: { flexDirection: 'row', gap: 12, marginTop: 18 },
  quickIntro: { flex: 1, justifyContent: 'center', gap: 6, backgroundColor: theme.colors.roseSoft, borderRadius: theme.radius.md, padding: 16 },
  quickTitle: { color: theme.colors.roseDark, fontSize: 16, fontWeight: '800' },
  quickBody: { color: theme.colors.inkMuted, fontSize: 12, lineHeight: 17 },
  quickActions: { flex: 1, gap: 8 },
  quickButton: { flex: 1, minHeight: 55, backgroundColor: theme.colors.roseDark, borderRadius: theme.radius.md, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, paddingHorizontal: 8 },
  quickButtonText: { color: theme.colors.white, fontSize: 14, fontWeight: '700', flexShrink: 1 },
  section: { marginTop: 28 },
  sectionTitle: { color: theme.colors.ink, fontSize: 19, fontWeight: '800', marginBottom: 12 },
  keywordBox: { borderWidth: 1, borderColor: theme.colors.border, borderRadius: theme.radius.lg, backgroundColor: theme.colors.card, overflow: 'hidden' },
  tabs: { flexDirection: 'row', borderBottomWidth: 1, borderColor: theme.colors.border },
  tab: { flex: 1, alignItems: 'center', justifyContent: 'center', minHeight: 48, borderBottomWidth: 3, borderColor: 'transparent' },
  tabActive: { borderColor: theme.colors.rose },
  tabText: { fontSize: 14, color: theme.colors.inkMuted, fontWeight: '700' },
  tabTextActive: { color: theme.colors.rose },
  emptyText: { color: theme.colors.inkMuted, fontSize: 13, textAlign: 'center', padding: 24, lineHeight: 19 },
  recentList: { paddingHorizontal: 16, paddingVertical: 4 },
  recentRow: { flexDirection: 'row', alignItems: 'center', minHeight: 44, gap: 12 },
  recentTerm: { flex: 1, paddingVertical: 10 },
  recentText: { color: theme.colors.ink, fontSize: 14 },
  rankLinks: { flexDirection: 'row', gap: 10 },
  rankLink: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: 8, minHeight: 72, padding: 12, backgroundColor: theme.colors.roseSoft, borderRadius: theme.radius.md },
  rankIcon: { fontSize: 20 },
  rankText: { flex: 1, color: theme.colors.roseDark, fontWeight: '800', fontSize: 14 },
  rail: { marginHorizontal: -6, paddingRight: 6 },
  product: { width: 168 },
});
