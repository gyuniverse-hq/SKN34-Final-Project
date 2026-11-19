import type { ComparisonAge } from '@/types/recommendationComparison';
import type { SkinV2Result } from '@/hooks/useSkinV2Recommendation';
import { SUPPORT_PRIORITY_CONCERNS } from '@/constants/skinSurvey';
import Ionicons from '@expo/vector-icons/Ionicons';
import { Stack, useFocusEffect, useLocalSearchParams, usePreventRemove, useRouter } from 'expo-router';
import { useCallback, useEffect, useMemo, useRef, useState, type ComponentRef } from 'react';
import { AppState, Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { SkinReportDetail } from '@/components/skin/SkinReportDetail';
import { SkinCareHighlights, SkinReportOverview } from '@/components/skin/SkinReportOverview';
import { SkinRoutine, SkinSolution } from '@/components/skin/SkinSolution';
import { ProductLineCard } from '@/components/shop/ProductLineCard';
import { Button } from '@/components/ui/Button';
import { InlineState } from '@/components/ui/InlineState';
import { Notice } from '@/components/ui/Notice';
import { LoadingState } from '@/components/ui/StateViews';
import { theme } from '@/constants/theme';
import { useSkinAccess } from '@/hooks/useSkinAccess';
import { offerAction } from '@/lib/confirm';
import { useSkinReport } from '@/hooks/useSkinReport';
import { useRecommendationCardFeedback } from '@/hooks/useRecommendationFeedback';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import { displayCareGoal } from '@/lib/skincare';
import { searchHref } from '@/lib/routes';
import type { SkinConcern } from '@/types';
import { useSkinPreviewStore } from '@/store/skinPreviewStore';

/** Summary → care priorities → solution / numeric details. Examples never enter storage. */
export default function SkinRecommendationsScreen() {
  const router = useRouter();
  const { t } = useI18n();
  const access = useSkinAccess();
  const flow = useSkinReport(access.subscribed);
  const { freeTrial } = useLocalSearchParams<{ freeTrial?: string }>();
  const [invited, setInvited] = useState(false);
  const offering = useRef(false);
  const shouldOffer = freeTrial === '1' && flow.live && !access.subscribed && !invited;
  const disablePrevention = usePreventRemove(shouldOffer, ({ repeat }) => invite(repeat));
  function invite(leave: () => void) {
    if (!shouldOffer) { leave(); return; }
    if (offering.current) return;
    offering.current = true;
    const finish = (action: () => void) => {
      setInvited(true);
      disablePrevention();
      action();
    };
    offerAction(t('skinAccess.reportInvite'), t('skinAccess.viewMembership'), t('skinAccess.later'),
      () => finish(() => router.replace('/membership')), () => finish(leave));
  }
  useFocusEffect(useCallback(() => () => { useSkinPreviewStore.getState().clear(); }, []));
  useEffect(() => {
    const listener = AppState.addEventListener('change', state => {
      if (state !== 'active') useSkinPreviewStore.getState().clear();
    });
    return () => listener.remove();
  }, []);
  const [tab, setTab] = useState<'solution' | 'results'>('solution');
  const [expanded, setExpanded] = useState(true);
  const [history, setHistory] = useState(false);
  const [tabsHeight, setTabsHeight] = useState(0);
  const scroll = useRef<ComponentRef<typeof ScrollView>>(null);
  const tabsY = useRef(0);
  const switchTab = (id: 'solution' | 'results') => {
    setTab(id);
    scroll.current?.scrollTo({ y: tabsY.current, animated: true });
  };
  const showDetail = (concern: SkinConcern) => {
    flow.setActive(concern); switchTab('results');
  };
  const start = () => invite(() => router.push('/skin-analysis'));
  const recommendation = flow.recommendation;
  const data = recommendation.query.data;
  const cards = useMemo(() => data?.matches.map((match, index) => ({
    productId: match.product.id, optionId: match.optionId, candidateId: match.candidateId, rank: index + 1,
  })), [data]);
  const { viewportRef, refresh, setCard, href } = useRecommendationCardFeedback(data?.history, cards, recommendation.owner,
    'skin_recommendations', tab === 'solution' && !history, tabsHeight);
  function productCard(match: SkinV2Result['matches'][number], index: number) {
    const item = cards![index];
    return <View key={match.product.id} collapsable={false} ref={node => setCard(item, node)}>
      <ProductLineCard product={{ ...match.product, priceKRW: match.priceKRW }} eyebrow={match.optionName}
        onPress={() => router.push(href(item))} />
    </View>;
  }
  if (flow.loading) return <LoadingState />;
  if (flow.loadFailed) return <SafeAreaView style={styles.screen}>
    <InlineState status="error" message={t('skin.loadFailed')} onRetry={() => { void flow.reload(); }} />
    <Button label={t('report.start')} onPress={start} />
  </SafeAreaView>;

  return <SafeAreaView style={styles.screen} edges={['top', 'bottom']}>
    <Stack.Screen options={{ headerShown: false }} />
    <View style={styles.header}>
      <Pressable accessibilityRole="button" accessibilityLabel={t('common.back')} style={styles.iconButton}
        onPress={() => invite(() => { if (router.canGoBack()) router.back(); else router.replace('/(tabs)'); })}>
        <Ionicons name="arrow-back" size={23} color={theme.colors.ink} />
      </Pressable>
      <View style={styles.headerTitle}><Text style={styles.headerLabel}>{t('report.title')}</Text></View>
      <Pressable accessibilityRole="button" accessibilityLabel={t('report.latest')} onPress={() => setHistory(true)} style={styles.iconButton}>
        <Ionicons name="reader-outline" size={23} color={theme.colors.ink} />
      </Pressable>
      <Pressable accessibilityRole="button" accessibilityLabel={t('tabs.home')} onPress={() => invite(() => router.replace('/(tabs)'))} style={styles.iconButton}>
        <Ionicons name="home-outline" size={23} color={theme.colors.ink} />
      </Pressable>
    </View>
    <View ref={viewportRef} collapsable={false} style={styles.scroll}>
    <ScrollView ref={scroll} style={styles.scroll} contentContainerStyle={styles.page} stickyHeaderIndices={[2]}
      onScroll={refresh} scrollEventThrottle={100}>
      <SkinReportOverview report={flow.report} example={flow.example} expanded={expanded} onExpand={() => setExpanded(!expanded)} onStart={start} />
      <SkinCareHighlights metrics={flow.report.priorities} allMetrics={flow.report.metrics} onPress={showDetail} />
      <View style={styles.tabs} onLayout={(event) => {
        tabsY.current = event.nativeEvent.layout.y;
        setTabsHeight(event.nativeEvent.layout.height);
      }}>
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
            : !access.subscribed ? <Button label={t('skinAccess.viewMembership')} variant="secondary"
                onPress={() => { setInvited(true); disablePrevention(); router.push('/membership'); }} />
            : recommendation.problem === 'comparison.needDemographics' ? <View>
              <Text style={styles.caption}>{t('comparison.needDemographics')}</Text>
              <Text style={styles.panelTitle}>{t('comparison.age')}</Text>
              <View style={styles.choices}>{(['10대', '20대', '30대', '40대', '50대', '60대'] as ComparisonAge[]).map(age =>
                <Pressable key={age} accessibilityRole="radio" accessibilityState={{ checked: recommendation.age === age }}
                  onPress={() => recommendation.setAge(age)} style={[styles.choice, recommendation.age === age && styles.choiceSelected]}>
                  <Text>{t('comparison.decade', { age: parseInt(age, 10) })}</Text>
                </Pressable>)}</View>
              <Text style={styles.panelTitle}>{t('comparison.gender')}</Text>
              <View style={styles.choices}>{(['남성', '여성'] as const).map(gender =>
                <Pressable key={gender} accessibilityRole="radio" accessibilityState={{ checked: recommendation.gender === gender }}
                  onPress={() => recommendation.setGender(gender)} style={[styles.choice, recommendation.gender === gender && styles.choiceSelected]}>
                  <Text>{t(gender === '남성' ? 'comparison.male' : 'comparison.female')}</Text>
                </Pressable>)}</View>
            </View>
            : recommendation.problem ? <View>
              <Text accessibilityRole="alert" style={styles.caption}>{t(recommendation.problem as TranslationKey)}</Text>
              <Button label={t('report.retake')} variant="secondary" onPress={start} />
            </View>
            : recommendation.query.isPending ? <InlineState status="loading" />
            : recommendation.query.isError ? <InlineState status="error" onRetry={() => recommendation.query.refetch()} />
              : data && <>
                <View style={styles.concernPanel}>
                  <Text style={styles.panelTitle} accessibilityRole="header">{t('skincare.aiTop5')}</Text>
                  {data.matches.length ? <>
                    <Text style={styles.caption}>{t('skincare.aiDescription')}</Text>
                    {data.matches.map(productCard)}
                  </> : <Text style={styles.caption}>{t('skincare.emptyAi')}</Text>}
                </View>
              </>}
          <Button label={t('skinFlow.skip')} variant="ghost" onPress={() => invite(() => router.push(searchHref({ source: 'skin' })))} />
        </View>
        <SkinRoutine />
      </View> : <SkinReportDetail metrics={flow.report.metrics} active={flow.activeConcern} onChange={flow.setActive} preview={flow.preview} />}
      <View style={styles.footer}>
        {__DEV__ ? <Button label={t('comparison.title')} variant="secondary"
          onPress={() => invite(() => router.push('/dev/recommendation-comparison'))} /> : null}
        <Notice title={t('skinFlow.notMedicalTitle')} body={t('skinFlow.notMedicalBody')} />
        <Button label={t('report.retake')} variant="secondary" onPress={start} />
        <Button label={t('report.top')} variant="ghost" icon="arrow-up" onPress={() => scroll.current?.scrollTo({ y: 0, animated: true })} />
      </View>
    </ScrollView>
    </View>
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
  choices: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginVertical: 8 },
  choice: { paddingVertical: 8, paddingHorizontal: 12, borderWidth: 1, borderColor: theme.colors.border, borderRadius: 16 },
  choiceSelected: { borderColor: theme.colors.rose, backgroundColor: theme.colors.roseSoft },
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
