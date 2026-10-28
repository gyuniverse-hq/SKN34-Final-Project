import Ionicons from '@expo/vector-icons/Ionicons';
import { useCameraPermissions } from 'expo-camera';
import * as Haptics from 'expo-haptics';
import { useFocusEffect, useLocalSearchParams, useRouter } from 'expo-router';
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  ActivityIndicator,
  AppState,
  Linking,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ArFaceView } from '@/components/ar/ArFaceView';
import type { ArStatus } from '@/components/ar/faceTrackerHtml';
import { SwatchFallback } from '@/components/ar/SwatchFallback';
import { Button } from '@/components/ui/Button';
import { Chip } from '@/components/ui/Chip';
import { theme } from '@/constants/theme';
import { useArRouteSelection } from '@/hooks/useArRouteSelection';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import { useProducts } from '@/lib/queries';
import { MAKEUP_ZONES, parseFlag, parseId, productHref, recommendationsHref } from '@/lib/routes';
import { useCartStore } from '@/store/cartStore';
import { useMakeupStore } from '@/store/makeupStore';
import { useSettingsStore } from '@/store/settingsStore';
import type { MakeupZone } from '@/types';

type Mode = 'direct' | 'chat';

const CHAT_EXAMPLES: TranslationKey[] = ['ar.chatExample1', 'ar.chatExample2', 'ar.chatExample3'];
const LEVELS: { key: TranslationKey; value: number }[] = [
  { key: 'ar.light', value: 0.35 },
  { key: 'ar.medium', value: 0.6 },
  { key: 'ar.bold', value: 0.85 },
];

function useCameraActive() {
  const [focused, setFocused] = useState(false);
  const [appActive, setAppActive] = useState(AppState.currentState === 'active');
  useFocusEffect(
    useCallback(() => {
      setFocused(true);
      return () => setFocused(false);
    }, [])
  );
  useEffect(() => {
    const sub = AppState.addEventListener('change', (state) => setAppActive(state === 'active'));
    return () => sub.remove();
  }, []);
  return focused && appActive;
}

/** `/ar?productId&shadeId&compare=1`: opened from home, a look, or a product ("Try in AR"). */
export default function ArTryOnScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{ compare?: string; productId?: string; shadeId?: string }>();
  const routeProductId = parseId(params.productId);
  const routeShadeId = parseId(params.shadeId);
  const { t } = useI18n();
  const cameraConsent = useSettingsStore((s) => s.cameraConsent);
  const setCameraConsent = useSettingsStore((s) => s.setCameraConsent);
  const [permission, requestPermission] = useCameraPermissions();
  const cameraActive = useCameraActive();
  const routeSelection = useArRouteSelection(routeProductId, routeShadeId);
  const routeZone = routeSelection.product.data?.makeupZone ?? undefined;
  const compareParam = parseFlag(params.compare);
  const [status, setStatus] = useState<ArStatus>('loading');
  const [arKey, setArKey] = useState(0);
  const [swatchOnly, setSwatchOnly] = useState(false);
  const [compare, setCompare] = useState(compareParam);
  const [zone, setZone] = useState<MakeupZone>(routeZone ?? 'lip');
  const [added, setAdded] = useState(false);
  const [mode, setMode] = useState<Mode>('direct');
  const [draft, setDraft] = useState('');

  // Follow new route params (a later "Try in AR" on the already-mounted tab) without an effect.
  const [seenParams, setSeenParams] = useState({ compare: compareParam, zone: routeZone });
  if (seenParams.compare !== compareParam || seenParams.zone !== routeZone) {
    setSeenParams({ compare: compareParam, zone: routeZone });
    if (compareParam) setCompare(true);
    if (routeZone) setZone(routeZone);
  }

  const { makeup, selections, activeLook, applyShade, setIntensity, clearZone } = useMakeupStore();
  const addMany = useCartStore((s) => s.addMany);
  const products = useProducts();

  const tryOnProducts = useMemo(() => (products.data ?? []).filter((p) => p.makeupZone), [products.data]);
  const zoneSwatches = useMemo(
    () =>
      tryOnProducts
        .filter((p) => p.makeupZone === zone)
        .flatMap((p) => p.shades.map((shade) => ({ product: p, shade }))),
    [tryOnProducts, zone]
  );

  useEffect(() => {
    if (routeProductId || makeup.lip || makeup.blush || makeup.eyeshadow) return;
    const firstLip = tryOnProducts.find((p) => p.makeupZone === 'lip');
    if (firstLip?.shades[0]) applyShade(firstLip, firstLip.shades[0]);
  }, [routeProductId, tryOnProducts, makeup, applyShade]);

  useFocusEffect(
    useCallback(() => {
      setStatus('loading');
    }, [])
  );

  useEffect(() => {
    if (!added) return;
    const timer = setTimeout(() => setAdded(false), 2400);
    return () => clearTimeout(timer);
  }, [added]);

  const isWeb = Platform.OS === 'web';
  const permissionGranted = isWeb || permission?.granted;
  const permissionBlocked = !isWeb && permission && !permission.granted && !permission.canAskAgain;

  const onAllow = async () => {
    setCameraConsent(true);
    setSwatchOnly(false);
    if (!isWeb && !permission?.granted) await requestPermission();
  };

  const retry = () => {
    setStatus('loading');
    setArKey((k) => k + 1);
  };

  const backToProduct = () => {
    if (router.canGoBack()) router.back();
    else if (routeProductId) router.push(productHref(routeProductId, routeShadeId));
  };

  const selectionItems = Object.values(selections).filter(Boolean);
  const onAddSelection = () => {
    if (added) {
      router.push('/cart');
      return;
    }
    addMany(
      selectionItems.map((s) => ({
        productId: s!.productId,
        shadeId: s!.shadeId,
        addedFromLookId: activeLook?.id,
      }))
    );
    setAdded(true);
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
  };

  const currentIntensity = makeup[zone]?.intensity;
  const zoneSelection = selections[zone];
  const openRecommendations = () => {
    if (!zoneSelection) return;
    router.push(
      recommendationsHref({
        productId: zoneSelection.productId,
        shadeId: zoneSelection.shadeId,
        zone,
        intensity: currentIntensity,
      })
    );
  };

  let stage: ReactNode;
  if (swatchOnly) {
    stage = (
      <View style={styles.fill}>
        <SwatchFallback message={t('ar.swatchOnly')} />
        <View style={styles.stageActions}>
          <Button label={t('ar.useCamera')} icon="camera-outline" variant="secondary" compact onPress={onAllow} />
        </View>
      </View>
    );
  } else if (!cameraConsent || (!permissionGranted && !permissionBlocked)) {
    stage = (
      <ScrollView contentContainerStyle={styles.consent}>
        <Ionicons name="scan-circle-outline" size={52} color={theme.colors.rose} />
        <Text style={styles.consentTitle}>{t('ar.consentTitle')}</Text>
        {(['ar.consentPoint1', 'ar.consentPoint2', 'ar.consentPoint3'] as const).map((key) => (
          <View key={key} style={styles.point}>
            <Ionicons name="shield-checkmark-outline" size={18} color={theme.colors.success} />
            <Text style={styles.pointText}>{t(key)}</Text>
          </View>
        ))}
        <Button label={t('ar.allowCamera')} icon="camera-outline" onPress={onAllow} style={styles.consentBtn} />
        <Button label={t('ar.withoutCamera')} variant="ghost" onPress={() => setSwatchOnly(true)} />
      </ScrollView>
    );
  } else if (permissionBlocked || status === 'denied') {
    stage = (
      <View style={styles.consent}>
        <Ionicons name="videocam-off-outline" size={44} color={theme.colors.inkFaint} />
        <Text style={styles.pointText}>{t('ar.cameraDenied')}</Text>
        {!isWeb ? (
          <Button label={t('ar.openSettings')} variant="secondary" onPress={() => Linking.openSettings()} style={styles.consentBtn} />
        ) : null}
        <Button label={t('ar.withoutCamera')} variant="ghost" onPress={() => setSwatchOnly(true)} />
      </View>
    );
  } else if (status === 'unavailable') {
    stage = (
      <View style={styles.fill}>
        <SwatchFallback message={t('ar.unavailable')} />
        <View style={styles.stageActions}>
          <Button label={t('common.retry')} icon="refresh" variant="secondary" compact onPress={retry} />
          {routeProductId ? (
            <Button label={t('ar.backToProduct')} variant="secondary" compact onPress={backToProduct} />
          ) : null}
        </View>
      </View>
    );
  } else if (cameraActive) {
    stage = (
      <View style={styles.camera}>
        <ArFaceView key={arKey} makeup={makeup} compare={compare} onStatus={setStatus} />
        {compare ? (
          <>
            <View pointerEvents="none" style={[styles.compareLabel, styles.beforeLabel]}>
              <Text style={styles.compareLabelText}>{t('idol.before')}</Text>
            </View>
            <View pointerEvents="none" style={[styles.compareLabel, styles.afterLabel]}>
              <Text style={styles.compareLabelText}>{t('idol.after')}</Text>
            </View>
            <View pointerEvents="none" style={styles.splitLine} />
          </>
        ) : null}
        {status === 'loading' ? (
          <View style={styles.overlay} pointerEvents="none">
            <ActivityIndicator color={theme.colors.white} />
            <Text style={styles.overlayText}>{t('ar.loading')}</Text>
          </View>
        ) : null}
        {status === 'no-face' ? (
          <View style={styles.noFace}>
            <Text style={styles.hintText}>{t('ar.noFace')}</Text>
            <View style={styles.noFaceActions}>
              <Pressable onPress={retry} accessibilityRole="button" style={styles.pillBtn}>
                <Text style={styles.pillBtnText}>{t('common.retry')}</Text>
              </Pressable>
              <Pressable onPress={() => setSwatchOnly(true)} accessibilityRole="button" style={styles.pillBtn}>
                <Text style={styles.pillBtnText}>{t('ar.viewSwatches')}</Text>
              </Pressable>
            </View>
          </View>
        ) : null}
        <View style={styles.liveBadge} pointerEvents="none">
          <View style={styles.liveDot} />
          <Text style={styles.liveText}>{t('ar.live')}</Text>
        </View>
        {status !== 'no-face' ? (
          <Pressable
            onPress={() => setCompare((value) => !value)}
            accessibilityRole="button"
            accessibilityLabel={t('ar.compare')}
            accessibilityState={{ selected: compare }}
            style={styles.compareBtn}>
            <Ionicons name="contrast-outline" size={18} color={theme.colors.white} />
            <Text style={styles.compareText}>{compare ? t('idol.fullAr') : t('idol.compare')}</Text>
          </Pressable>
        ) : null}
      </View>
    );
  } else {
    stage = <View style={styles.camera} />;
  }

  return (
    <SafeAreaView style={styles.screen} edges={['top']}>
      <View style={styles.stage}>
        {stage}
        {router.canGoBack() ? (
          <Pressable
            onPress={() => router.back()}
            accessibilityRole="button"
            accessibilityLabel={t('common.back')}
            hitSlop={8}
            style={styles.backBtn}>
            <Ionicons name="chevron-back" size={22} color={theme.colors.white} />
          </Pressable>
        ) : null}
      </View>

      <View style={styles.panel}>
        <View style={styles.modeRow}>
          {(['direct', 'chat'] as const).map((m) => (
            <Pressable
              key={m}
              onPress={() => setMode(m)}
              accessibilityRole="tab"
              accessibilityState={{ selected: mode === m }}
              style={[styles.modeTab, mode === m && styles.modeTabActive]}>
              <Ionicons
                name={m === 'chat' ? 'chatbubbles-outline' : 'color-palette-outline'}
                size={16}
                color={mode === m ? theme.colors.white : theme.colors.inkMuted}
              />
              <Text style={[styles.modeText, mode === m && styles.modeTextActive]}>
                {t(m === 'chat' ? 'ar.mode.chat' : 'ar.mode.direct')}
              </Text>
            </Pressable>
          ))}
        </View>

        {activeLook ? (
          <Text style={styles.lookBanner} numberOfLines={1}>
            {t('ar.lookApplied', { title: activeLook.title })}
          </Text>
        ) : null}
        {routeSelection.shadeMissing ? (
          <Text style={styles.warnBanner} accessibilityRole="alert">
            {t('catalog.shadeMissingPicked')}
          </Text>
        ) : null}
        {routeSelection.notTryOn ? (
          <Text style={styles.warnBanner} accessibilityRole="alert">
            {t('ar.notTryOn')}
          </Text>
        ) : null}
        {routeSelection.product.isError ? (
          <Text style={styles.warnBanner} accessibilityRole="alert">
            {t('catalog.productUnavailable')}
          </Text>
        ) : null}

        {mode === 'chat' ? (
          <View style={styles.chat}>
            <Text style={styles.chatTitle}>{t('ar.chatTitle')}</Text>
            <Text style={styles.chatBody}>{t('ar.chatBody')}</Text>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chatExamples}>
              {CHAT_EXAMPLES.map((key) => (
                <Chip key={key} label={t(key)} onPress={() => setDraft(t(key))} />
              ))}
            </ScrollView>
            <View style={styles.chatInputRow}>
              <Pressable accessibilityRole="button" accessibilityLabel={t('ar.mic')} style={styles.micBtn}>
                <Ionicons name="mic" size={22} color={theme.colors.white} />
              </Pressable>
              <TextInput
                value={draft}
                onChangeText={setDraft}
                placeholder={t('ar.chatPlaceholder')}
                placeholderTextColor={theme.colors.inkFaint}
                style={styles.chatInput}
                returnKeyType="send"
              />
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={t('ar.send')}
                disabled={!draft.trim()}
                style={[styles.sendBtn, !draft.trim() && { opacity: 0.4 }]}>
                <Ionicons name="arrow-up" size={20} color={theme.colors.white} />
              </Pressable>
            </View>
          </View>
        ) : (
          <>
            <View style={styles.zoneRow}>
              {MAKEUP_ZONES.map((z) => (
                <Pressable
                  key={z}
                  onPress={() => setZone(z)}
                  accessibilityRole="tab"
                  accessibilityState={{ selected: zone === z }}
                  style={[styles.zoneTab, zone === z && styles.zoneTabActive]}>
                  <View style={[styles.zoneDot, { backgroundColor: makeup[z]?.hex ?? theme.colors.border }]} />
                  <Text style={[styles.zoneText, zone === z && styles.zoneTextActive]}>
                    {t(`ar.zone.${z}` as TranslationKey)}
                  </Text>
                </Pressable>
              ))}
            </View>

            {products.isError ? (
              <View style={styles.inlineRow}>
                <Text style={styles.noProducts}>{t('common.errorTitle')}</Text>
                <Button label={t('common.retry')} variant="ghost" compact onPress={() => products.refetch()} />
              </View>
            ) : zoneSwatches.length === 0 && !products.isPending ? (
              <Text style={styles.noProducts}>{t('ar.noProducts')}</Text>
            ) : null}
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.swatches}>
              {zoneSwatches.map(({ product, shade }) => {
                const selected =
                  selections[zone]?.productId === product.id && selections[zone]?.shadeId === shade.id;
                return (
                  <Pressable
                    key={`${product.id}-${shade.id}`}
                    onPress={() => {
                      applyShade(product, shade);
                      Haptics.selectionAsync().catch(() => {});
                    }}
                    accessibilityRole="button"
                    accessibilityLabel={`${product.brand} ${product.name} ${shade.name}`}
                    accessibilityState={{ selected }}
                    style={styles.swatchItem}>
                    <View style={[styles.swatchRing, selected && styles.swatchRingActive]}>
                      <View style={[styles.swatch, { backgroundColor: shade.hex }]} />
                    </View>
                    <Text style={styles.swatchBrand} numberOfLines={1}>
                      {product.brand}
                    </Text>
                    <Text style={styles.swatchName} numberOfLines={1}>
                      {shade.name}
                    </Text>
                  </Pressable>
                );
              })}
            </ScrollView>

            <View style={styles.levels}>
              <Text style={styles.levelsLabel}>{t('ar.intensity')}</Text>
              <Chip label={t('ar.off')} selected={!makeup[zone]} onPress={() => clearZone(zone)} />
              {LEVELS.map((level) => (
                <Chip
                  key={level.key}
                  label={t(level.key)}
                  selected={
                    currentIntensity !== undefined && Math.abs(currentIntensity - level.value) < 0.13
                  }
                  onPress={() => {
                    if (makeup[zone]) {
                      setIntensity(zone, level.value);
                    } else if (zoneSwatches[0]) {
                      applyShade(zoneSwatches[0].product, zoneSwatches[0].shade);
                      setIntensity(zone, level.value);
                    }
                  }}
                />
              ))}
            </View>

            <Text style={styles.disclaimer}>{t('ar.disclaimer')}</Text>

            <View style={styles.actions}>
              <Button
                label={added ? t('looks.viewCart') : t('ar.addSelection')}
                icon={added ? 'checkmark' : 'cart-outline'}
                disabled={selectionItems.length === 0}
                onPress={onAddSelection}
                style={{ flex: 1 }}
              />
              <Button
                label={t('ar.similar')}
                variant="secondary"
                icon="color-filter-outline"
                disabled={!zoneSelection}
                onPress={openRecommendations}
              />
            </View>
          </>
        )}
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.ink },
  stage: { flex: 1, margin: 10, marginBottom: 0, borderRadius: theme.radius.lg, overflow: 'hidden', backgroundColor: theme.colors.black },
  fill: { flex: 1 },
  camera: { flex: 1, backgroundColor: theme.colors.black },
  consent: { flexGrow: 1, padding: 28, alignItems: 'center', justifyContent: 'center', gap: 12, backgroundColor: theme.colors.surface },
  consentTitle: { fontSize: theme.font.h2, fontWeight: '800', color: theme.colors.ink, textAlign: 'center', marginBottom: 6 },
  point: { flexDirection: 'row', gap: 10, alignItems: 'flex-start', alignSelf: 'stretch' },
  pointText: { flex: 1, fontSize: theme.font.body, color: theme.colors.inkMuted, lineHeight: 21, textAlign: 'left' },
  consentBtn: { alignSelf: 'stretch', marginTop: 10 },
  stageActions: { position: 'absolute', bottom: 14, left: 0, right: 0, flexDirection: 'row', justifyContent: 'center', gap: 8 },
  backBtn: { position: 'absolute', top: 10, right: 10, width: theme.hitTarget, height: theme.hitTarget, borderRadius: theme.hitTarget / 2, backgroundColor: theme.colors.overlay, alignItems: 'center', justifyContent: 'center' },
  overlay: { position: 'absolute', top: 0, right: 0, bottom: 0, left: 0, alignItems: 'center', justifyContent: 'center', gap: 10, backgroundColor: 'rgba(0,0,0,0.35)' },
  overlayText: { color: theme.colors.white, fontSize: theme.font.small, fontWeight: '600' },
  noFace: { position: 'absolute', bottom: 16, left: 16, right: 16, alignItems: 'center', gap: 8, backgroundColor: theme.colors.overlay, padding: 12, borderRadius: theme.radius.md },
  noFaceActions: { flexDirection: 'row', gap: 8 },
  pillBtn: { minHeight: 36, paddingHorizontal: 14, justifyContent: 'center', borderRadius: theme.radius.pill, backgroundColor: 'rgba(255,255,255,0.18)' },
  pillBtnText: { color: theme.colors.white, fontSize: theme.font.small, fontWeight: '700' },
  hintText: { color: theme.colors.white, fontSize: theme.font.small, fontWeight: '600', textAlign: 'center' },
  liveBadge: { position: 'absolute', top: 12, left: 12, flexDirection: 'row', alignItems: 'center', gap: 6, backgroundColor: theme.colors.overlay, paddingHorizontal: 10, paddingVertical: 5, borderRadius: theme.radius.pill },
  liveDot: { width: 7, height: 7, borderRadius: 4, backgroundColor: '#4ADE80' },
  liveText: { color: theme.colors.white, fontSize: 11, fontWeight: '600' },
  compareBtn: { position: 'absolute', bottom: 14, alignSelf: 'center', flexDirection: 'row', alignItems: 'center', gap: 6, backgroundColor: theme.colors.overlay, paddingHorizontal: 14, minHeight: 40, borderRadius: theme.radius.pill },
  compareText: { color: theme.colors.white, fontSize: theme.font.small, fontWeight: '600' },
  compareLabel: { position: 'absolute', top: 44, paddingHorizontal: 9, paddingVertical: 5, borderRadius: theme.radius.pill, backgroundColor: theme.colors.overlay },
  beforeLabel: { left: 12 },
  afterLabel: { right: 12 },
  compareLabelText: { color: theme.colors.white, fontSize: 11, fontWeight: '800' },
  splitLine: { position: 'absolute', top: 0, bottom: 0, left: '50%', width: 2, marginLeft: -1, backgroundColor: 'rgba(255,255,255,0.9)' },
  panel: { backgroundColor: theme.colors.surface, borderTopLeftRadius: theme.radius.lg, borderTopRightRadius: theme.radius.lg, marginTop: 10, paddingTop: 14, paddingBottom: 12, gap: 10 },
  lookBanner: { marginHorizontal: 16, fontSize: 12, fontWeight: '700', color: theme.colors.rose },
  warnBanner: { marginHorizontal: 16, fontSize: 12, fontWeight: '600', color: theme.colors.warning },
  zoneRow: { flexDirection: 'row', marginHorizontal: 16, backgroundColor: theme.colors.surfaceAlt, borderRadius: theme.radius.md, padding: 3 },
  zoneTab: { flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, minHeight: 38, borderRadius: 10 },
  zoneTabActive: { backgroundColor: theme.colors.card, ...theme.shadow },
  zoneDot: { width: 10, height: 10, borderRadius: 5 },
  zoneText: { fontSize: theme.font.small, fontWeight: '600', color: theme.colors.inkMuted },
  zoneTextActive: { color: theme.colors.ink },
  swatches: { gap: 10, paddingHorizontal: 16 },
  swatchItem: { width: 70, alignItems: 'center' },
  swatchRing: { width: 50, height: 50, borderRadius: 25, borderWidth: 2, borderColor: 'transparent', alignItems: 'center', justifyContent: 'center' },
  swatchRingActive: { borderColor: theme.colors.rose },
  swatch: { width: 40, height: 40, borderRadius: 20, borderWidth: 1, borderColor: 'rgba(0,0,0,0.08)' },
  swatchBrand: { fontSize: 10, color: theme.colors.inkFaint, marginTop: 4 },
  swatchName: { fontSize: 11, color: theme.colors.ink, fontWeight: '600' },
  levels: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 16, flexWrap: 'wrap' },
  levelsLabel: { fontSize: 12, fontWeight: '700', color: theme.colors.inkMuted, marginRight: 4 },
  disclaimer: { marginHorizontal: 16, fontSize: 11, lineHeight: 16, color: theme.colors.inkFaint },
  actions: { flexDirection: 'row', gap: 10, paddingHorizontal: 16 },
  inlineRow: { flexDirection: 'row', alignItems: 'center', gap: 8, marginHorizontal: 16 },
  noProducts: { marginHorizontal: 16, fontSize: theme.font.small, color: theme.colors.inkMuted },
  modeRow: { flexDirection: 'row', gap: 8, marginHorizontal: 16 },
  modeTab: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 14, minHeight: 36, borderRadius: theme.radius.pill, backgroundColor: theme.colors.surfaceAlt },
  modeTabActive: { backgroundColor: theme.colors.rose },
  modeText: { fontSize: theme.font.small, fontWeight: '700', color: theme.colors.inkMuted },
  modeTextActive: { color: theme.colors.white },
  chat: { paddingHorizontal: 16, gap: 8 },
  chatTitle: { fontSize: theme.font.body, fontWeight: '800', color: theme.colors.ink },
  chatBody: { fontSize: theme.font.small, color: theme.colors.inkMuted, lineHeight: 19 },
  chatExamples: { gap: 8, paddingVertical: 4 },
  chatInputRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  micBtn: { width: 46, height: 46, borderRadius: 23, backgroundColor: theme.colors.rose, alignItems: 'center', justifyContent: 'center' },
  chatInput: { flex: 1, minHeight: 46, borderRadius: theme.radius.pill, borderWidth: 1, borderColor: theme.colors.border, backgroundColor: theme.colors.card, paddingHorizontal: 16, fontSize: theme.font.body, color: theme.colors.ink },
  sendBtn: { width: 40, height: 40, borderRadius: 20, backgroundColor: theme.colors.ink, alignItems: 'center', justifyContent: 'center' },
});
