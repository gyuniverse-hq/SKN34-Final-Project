import Ionicons from '@expo/vector-icons/Ionicons';
import { Stack, useRouter } from 'expo-router';
import { useRef, useState, type ComponentRef } from 'react';
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ConcernPicker } from '@/components/skin/ConcernPicker';
import { SkinReportDetail } from '@/components/skin/SkinReportDetail';
import { SkinCareHighlights, SkinReportOverview } from '@/components/skin/SkinReportOverview';
import { SkinSampleProducts } from '@/components/skin/SkinSampleProducts';
import { SkinSolution } from '@/components/skin/SkinSolution';
import { ProductLineCard } from '@/components/shop/ProductLineCard';
import { Button } from '@/components/ui/Button';
import { InlineState } from '@/components/ui/InlineState';
import { Notice } from '@/components/ui/Notice';
import { LoadingState } from '@/components/ui/StateViews';
import { theme } from '@/constants/theme';
import { useSkinReport } from '@/hooks/useSkinReport';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import { productHref, searchHref, SKIN_CONCERNS } from '@/lib/routes';
import type { SkinConcern } from '@/types';

/** Summary → care priorities → solution / numeric details. Examples never enter storage. */
export default function SkinRecommendationsScreen() {
  const router = useRouter();
  const { t } = useI18n();
  const flow = useSkinReport();
  const [tab, setTab] = useState<'solution' | 'results'>('solution');
  const [expanded, setExpanded] = useState(true);
  const [adjusting, setAdjusting] = useState(false);
  const [history, setHistory] = useState(false);
  const scroll = useRef<ComponentRef<typeof ScrollView>>(null);
  const tabsY = useRef(0);
  const switchTab = (id: 'solution' | 'results') => {
    setTab(id);
    scroll.current?.scrollTo({ y: tabsY.current, animated: true });
  };
  const showDetail = (concern: SkinConcern) => {
    flow.setActive(concern); switchTab('results');
  };
  const start = () => router.push('/skin-consent');
  if (flow.loading) return <LoadingState />;
  if (flow.loadFailed) return <SafeAreaView style={styles.screen}>
    <InlineState status="error" message={t('skin.loadFailed')} onRetry={() => { void flow.reload(); }} />
    <Button label={t('report.start')} onPress={start} />
  </SafeAreaView>;

  return <SafeAreaView style={styles.screen} edges={['top', 'bottom']}>
    <Stack.Screen options={{ headerShown: false }} />
    <View style={styles.header}>
      <Pressable accessibilityRole="button" accessibilityLabel={t('common.back')} style={styles.iconButton}
        onPress={() => { if (router.canGoBack()) router.back(); else router.replace('/(tabs)'); }}>
        <Ionicons name="arrow-back" size={23} color={theme.colors.ink} />
      </Pressable>
      <View style={styles.headerTitle}><Text style={styles.headerLabel}>{t('report.title')}</Text></View>
      <Pressable accessibilityRole="button" accessibilityLabel={t('report.latest')} onPress={() => setHistory(true)} style={styles.iconButton}>
        <Ionicons name="reader-outline" size={23} color={theme.colors.ink} />
      </Pressable>
      <Pressable accessibilityRole="button" accessibilityLabel={t('tabs.home')} onPress={() => router.replace('/(tabs)')} style={styles.iconButton}>
        <Ionicons name="home-outline" size={23} color={theme.colors.ink} />
      </Pressable>
    </View>
    <ScrollView ref={scroll} style={styles.scroll} contentContainerStyle={styles.page} stickyHeaderIndices={[2]}>
      <SkinReportOverview report={flow.report} example={flow.example} expanded={expanded} onExpand={() => setExpanded(!expanded)} onStart={start} />
      <SkinCareHighlights metrics={flow.report.priorities} onPress={showDetail} />
      <View style={styles.tabs} onLayout={(event) => { tabsY.current = event.nativeEvent.layout.y; }}>
        <View style={styles.tabsRow}>
          {(['solution', 'results'] as const).map((id) => <Pressable key={id} onPress={() => switchTab(id)} accessibilityRole="tab" accessibilityState={{ selected: tab === id }} style={[styles.tab, tab === id && styles.tabOn]}>
            <Text style={[styles.tabLabel, tab === id && styles.tabLabelOn]}>{t(`report.${id}`)}</Text>
          </Pressable>)}
        </View>
      </View>
      {tab === 'solution' ? <View>
        <SkinSolution concerns={SKIN_CONCERNS} active={flow.activeConcern} onChange={flow.setActive} ingredients={flow.ingredients} />
        <View style={styles.products}>
          <Text style={styles.title} accessibilityRole="header">{t('report.products')}</Text>
          <Pressable onPress={() => setAdjusting(!adjusting)} style={styles.adjust} accessibilityRole="button" accessibilityState={{ expanded: adjusting }}>
            <Text style={styles.link}>{t('report.adjust')}</Text><Ionicons name={adjusting ? 'chevron-up' : 'chevron-down'} size={18} color={theme.colors.rose} />
          </Pressable>
          {adjusting ? <ConcernPicker concerns={SKIN_CONCERNS} selected={flow.selected} suggested={flow.report.concerns} onToggle={flow.toggle} /> : null}
          {!flow.live ? <>
            <Text style={styles.sampleLabel}>{t('report.sampleProducts')}</Text>
            <Text style={styles.caption}>{t('report.sampleProductsBody')}</Text>
            {flow.samples.length ? <SkinSampleProducts matches={flow.samples} /> : <InlineState status="empty" message={t('skinRec.noConcerns')} />}
          </> : flow.recommendations.isPending ? <InlineState status="loading" />
            : flow.recommendations.isError ? <InlineState status="error" onRetry={() => flow.recommendations.refetch()} />
              : flow.recommendations.data?.status !== 'ok' ? <InlineState status="empty" message={t(
                flow.recommendations.data?.status === 'empty_catalog' ? 'skinRec.emptyCatalog'
                  : flow.recommendations.data?.status === 'no_concerns' ? 'skinRec.noConcerns' : 'skinRec.noMatches'
              )} /> : flow.recommendations.data.matches.map(({ product, matchedConcerns }) => <ProductLineCard key={product.id} product={product}
                note={t('skinRec.matched', { count: matchedConcerns.length })}
                badges={matchedConcerns.map((c) => ({ label: t(`concern.${c}` as TranslationKey), tone: 'brand' }))}
                onPress={() => router.push(productHref(product.id))} />)}
          <Button label={t('report.liveProducts')} variant="secondary" disabled={flow.selected.length === 0} loading={flow.recommendations.isFetching} onPress={flow.findProducts} />
          {flow.live ? <Button label={t('report.showSamples')} variant="ghost" onPress={flow.showSamples} /> : null}
          <Button label={t('skinFlow.skip')} variant="ghost" onPress={() => router.push(searchHref({ source: 'skin' }))} />
        </View>
      </View> : <SkinReportDetail metrics={flow.report.metrics} active={flow.activeConcern} onChange={flow.setActive} />}
      <View style={styles.footer}>
        <Notice title={t('skinFlow.notMedicalTitle')} body={t('skinFlow.notMedicalBody')} />
        <Button label={t('report.retake')} variant="secondary" onPress={start} />
        <Button label={t('report.top')} variant="ghost" icon="arrow-up" onPress={() => scroll.current?.scrollTo({ y: 0, animated: true })} />
      </View>
    </ScrollView>
    <Modal visible={history} transparent animationType="fade" onRequestClose={() => setHistory(false)}>
      <View style={styles.overlay}><View style={styles.dialog} accessibilityViewIsModal>
        <Text style={styles.title}>{t('report.latest')}</Text>
        <Text style={styles.caption}>{t('report.latestBody')}</Text>
        <Text style={styles.headerLabel}>{flow.example ? t('report.sample') : t('report.title')}</Text>
        <Button label={t('report.close')} onPress={() => setHistory(false)} />
      </View></View>
    </Modal>
  </SafeAreaView>;
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface }, scroll: { flex: 1 }, page: { width: '100%', maxWidth: 680, alignSelf: 'center' },
  header: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 12, minHeight: 64, gap: 2, width: '100%', maxWidth: 680, alignSelf: 'center', borderBottomWidth: 1, borderBottomColor: theme.colors.border },
  iconButton: { width: 44, height: 48, justifyContent: 'center', alignItems: 'center' },
  headerTitle: { flex: 1, alignItems: 'center', gap: 3 }, headerLabel: { fontSize: 15, fontWeight: '700', color: theme.colors.ink },
  tabs: { backgroundColor: theme.colors.surface, borderBottomWidth: 1, borderBottomColor: theme.colors.border },
  tabsRow: { flexDirection: 'row', width: '100%', paddingHorizontal: 24, gap: 24 },
  tab: { flex: 1, minWidth: 0, alignItems: 'center', paddingVertical: 18, borderBottomWidth: 3, borderBottomColor: 'transparent' }, tabOn: { borderBottomColor: theme.colors.rose },
  tabLabel: { fontSize: 15, fontWeight: '600', color: theme.colors.inkFaint }, tabLabelOn: { color: theme.colors.rose, fontWeight: '800' },
  products: { padding: 24, paddingTop: 0, gap: 16 }, title: { color: theme.colors.ink, fontSize: 21, fontWeight: '800', lineHeight: 30 },
  caption: { color: theme.colors.inkMuted, fontSize: 12, lineHeight: 20 }, sampleLabel: { color: theme.colors.accent, fontSize: 11, fontWeight: '800' },
  adjust: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', minHeight: 44, gap: 10 }, link: { color: theme.colors.rose, fontSize: 13, fontWeight: '700' },
  footer: { padding: 24, gap: 16, borderTopWidth: 1, borderTopColor: theme.colors.border },
  overlay: { flex: 1, backgroundColor: theme.colors.overlay, justifyContent: 'center', alignItems: 'center', padding: 24 },
  dialog: { width: '100%', maxWidth: 400, backgroundColor: theme.colors.surface, borderRadius: 20, padding: 24, gap: 20 },
});
