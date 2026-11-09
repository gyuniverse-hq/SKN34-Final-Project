import type { CareGoal, HybridMatch } from '@/types/skincare';
import { SUPPORT_PRIORITY_CONCERNS } from '@/constants/skinSurvey';
import Ionicons from '@expo/vector-icons/Ionicons';
import { Stack, useFocusEffect, useRouter } from 'expo-router';
import { useCallback, useEffect, useRef, useState, type ComponentRef } from 'react';
import { AppState, Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { SkinConcernRail, SkinReportDetail } from '@/components/skin/SkinReportDetail';
import { SkinCareHighlights, SkinReportOverview } from '@/components/skin/SkinReportOverview';
import { SkinRoutine, SkinSolution } from '@/components/skin/SkinSolution';
import { ProductLineCard } from '@/components/shop/ProductLineCard';
import { Button } from '@/components/ui/Button';
import { InlineState } from '@/components/ui/InlineState';
import { Notice } from '@/components/ui/Notice';
import { LoadingState } from '@/components/ui/StateViews';
import { theme } from '@/constants/theme';
import { useSkinReport } from '@/hooks/useSkinReport';
import { useI18n } from '@/lib/i18n';
import { displayCareGoal, displayCareGroups } from '@/lib/skincare';
import { productHref, searchHref } from '@/lib/routes';
import type { SkinConcern } from '@/types';
import { useSkinPreviewStore } from '@/store/skinPreviewStore';

/** Summary → care priorities → solution / numeric details. Examples never enter storage. */
export default function SkinRecommendationsScreen() {
  const router = useRouter();
  const { t } = useI18n();
  const flow = useSkinReport();
  useFocusEffect(useCallback(() => () => { useSkinPreviewStore.getState().clear(); }, []));
  useEffect(() => {
    const listener = AppState.addEventListener('change', state => {
      if (state !== 'active') useSkinPreviewStore.getState().clear();
    });
    return () => listener.remove();
  }, []);
  const [tab, setTab] = useState<'solution' | 'results'>('solution');
  const [browseGoal, setBrowseGoal] = useState<CareGoal>('dryness');
  const [expanded, setExpanded] = useState(true);
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
  const start = () => router.push('/skin-analysis');
  function productCard(match: HybridMatch, group?: CareGoal) {
    const reasons = group ? match.reasons.filter(r => displayCareGoal(r.goal) === group) : match.reasons;
    const note = [...new Set(reasons.map(reason => {
      const source = reason.sources[0];
      return t(`skincare.reason.${source}`, { goal: t(`support.priorityChoice.${displayCareGoal(reason.goal)}`) });
    }))].join('\n');
    return <ProductLineCard key={match.product.id} product={{ ...match.product, priceKRW: match.priceKRW }}
      eyebrow={match.optionName} note={note}
      onPress={() => router.push(productHref(match.product.id))} />;
  }
  const data = flow.recommendations.data;
  const browseGroup = data && displayCareGroups(data).find(group => group.goal === browseGoal);
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
      <SkinCareHighlights metrics={flow.report.priorities} allMetrics={flow.report.metrics} onPress={showDetail} />
      <View style={styles.tabs} onLayout={(event) => { tabsY.current = event.nativeEvent.layout.y; }}>
        <View style={styles.tabsRow}>
          {(['solution', 'results'] as const).map((id) => <Pressable key={id} onPress={() => switchTab(id)} accessibilityRole="tab" accessibilityState={{ selected: tab === id }} style={[styles.tab, tab === id && styles.tabOn]}>
            <Text style={[styles.tabLabel, tab === id && styles.tabLabelOn]}>{t(`report.${id}`)}</Text>
          </Pressable>)}
        </View>
      </View>
      {tab === 'solution' ? <View>
        <SkinSolution concerns={SUPPORT_PRIORITY_CONCERNS} active={displayCareGoal(flow.activeConcern)} onChange={flow.setActive} ingredients={flow.ingredients} />
        <View style={styles.products}>
          <Text style={styles.title} accessibilityRole="header">{t('report.products')}</Text>
          <Text style={styles.caption}>{t('skincare.disclosure')}</Text>
          {!flow.live ? <Text style={styles.caption}>{t('skincare.requestPrompt')}</Text>
            : flow.recommendations.isPending ? <InlineState status="loading" />
            : flow.recommendations.isError ? <InlineState status="error" onRetry={() => flow.recommendations.refetch()} />
              : data && <>
                <View style={styles.concernPanel}>
                  <Text style={styles.panelTitle} accessibilityRole="header">{t('skincare.aiTop5')}</Text>
                  {data.overallTop5.length ? <>
                    <Text style={styles.caption}>{t('skincare.aiDescription')}</Text>
                    {data.overallTop5.map(match => productCard(match))}
                  </> : <Text style={styles.caption}>{t('skincare.emptyAi')}</Text>}
                </View>
                <View style={styles.concernPanel}>
                  <Text style={styles.panelTitle} accessibilityRole="header">{t('skincare.concernTop5')}</Text>
                  <SkinConcernRail concerns={SUPPORT_PRIORITY_CONCERNS} active={browseGoal} onChange={setBrowseGoal} goalLabels />
                  {browseGroup?.status === 'ok' ? browseGroup.matches.map(match => productCard(match, browseGoal))
                    : <Text style={styles.caption}>{t(browseGroup?.status === 'no_matches' ? 'skincare.no_matches' : 'skincare.mapping_unavailable', { goal: t(`support.priorityChoice.${browseGoal}`) })}</Text>}
                </View>
              </>}
          <Button label={t('skinFlow.skip')} variant="ghost" onPress={() => router.push(searchHref({ source: 'skin' }))} />
        </View>
        <SkinRoutine />
      </View> : <SkinReportDetail metrics={flow.report.metrics} active={flow.activeConcern} onChange={flow.setActive} preview={flow.preview} />}
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
  caption: { color: theme.colors.inkMuted, fontSize: 12, lineHeight: 20 },
  concernPanel: { gap: 12 }, panelTitle: { color: theme.colors.ink, fontSize: 15, fontWeight: '700' },
  footer: { padding: 24, gap: 16, borderTopWidth: 1, borderTopColor: theme.colors.border },
  overlay: { flex: 1, backgroundColor: theme.colors.overlay, justifyContent: 'center', alignItems: 'center', padding: 24 },
  dialog: { width: '100%', maxWidth: 400, backgroundColor: theme.colors.surface, borderRadius: 20, padding: 24, gap: 20 },
});
