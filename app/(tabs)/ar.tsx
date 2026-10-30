import Ionicons from '@expo/vector-icons/Ionicons';
import { useCameraPermissions } from 'expo-camera';
import * as Haptics from 'expo-haptics';
import { LinearGradient } from 'expo-linear-gradient';
import { useFocusEffect, useLocalSearchParams, useNavigation, useRouter } from 'expo-router';
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import {
  ActivityIndicator,
  AppState,
  BackHandler,
  LayoutAnimation,
  Linking,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  UIManager,
  useWindowDimensions,
  View,
  type GestureResponderEvent,
} from 'react-native';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import { ArFaceView, type LightHint } from '@/components/ar/ArFaceView';
import { CoverageBar } from '@/components/ar/CoverageBar';
import { PracticePanel } from '@/components/ar/PracticePanel';
import type { ArStatus } from '@/components/ar/faceTrackerHtml';
import { SwatchFallback } from '@/components/ar/SwatchFallback';
import { Button } from '@/components/ui/Button';
import { Chip } from '@/components/ui/Chip';
import { DEMO_TAG } from '@/constants/demo';
import { TAB_BAR_STYLE, theme } from '@/constants/theme';
import { COLOR_FAMILIES, colorFamily, type ColorFamily } from '@/lib/colorFamily';
import { withDevTryOnFallback } from '@/lib/devCatalog';
import { formatKRW } from '@/lib/format';
import { LINER_LOOK_IDS, LINER_LOOKS, matchingLinerLook } from '@/lib/linerLooks';
import { SHADOW_FINISH_IDS, shadowFinishOf } from '@/lib/shadowFinishes';
import { findColorGaps, recommendShades, type LookLine } from '@/lib/colorGaps';
import { guideMessage } from '@/lib/drawGuide';
import { buildGuideSteps, guideText } from '@/lib/lookGuide';
import { practiceDrawStep, practiceZones, revealedMakeup, visit } from '@/lib/practice';
import { useArRouteSelection } from '@/hooks/useArRouteSelection';
import { MIN_TONE_CONF, rankFoundationShades, type SkinTone } from '@/lib/foundationMatch';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import { useProducts } from '@/lib/queries';
import { parseFlag, parseId, productHref, recommendationsHref } from '@/lib/routes';
import { useCartStore } from '@/store/cartStore';
import { AR_PAINT_ZONES, arPaintMakeup, isArPaintZone, MAKEUP_ZONES, useMakeupStore } from '@/store/makeupStore';
import { useSettingsStore } from '@/store/settingsStore';
import type { MakeupZone, Texture } from '@/types';

type Mode = 'direct' | 'chat';

const HIDDEN_TAB_BAR_STYLE = { ...TAB_BAR_STYLE, display: 'none' as const, height: 0 };

if (Platform.OS === 'android' && UIManager.setLayoutAnimationEnabledExperimental) {
  UIManager.setLayoutAnimationEnabledExperimental(true);
}

const CHAT_EXAMPLES: TranslationKey[] = ['ar.chatExample1', 'ar.chatExample2', 'ar.chatExample3'];
const TEXTURES: Texture[] = ['matte', 'velvet', 'cream', 'satin', 'sheer', 'glossy', 'shimmer'];
const BLUSH_INTENSITY_MIN = 0.15;
const BLUSH_KNOB = 20;
function mixHexTowardWhite(hex: string, amount: number): string {
  const n = Number.parseInt(hex.replace('#', '').slice(0, 6), 16);
  if (!Number.isFinite(n)) return '#FFFFFF';
  const mix = (c: number) => Math.round(c + (255 - c) * amount);
  const r = mix((n >> 16) & 255);
  const g = mix((n >> 8) & 255);
  const b = mix(n & 255);
  return `#${[r, g, b].map((c) => c.toString(16).padStart(2, '0')).join('')}`;
}

function blushIntensityFromX(x: number, width: number): number {
  if (width <= 0) return BLUSH_INTENSITY_MIN;
  const t = Math.min(1, Math.max(0, x / width));
  return BLUSH_INTENSITY_MIN + t * (1 - BLUSH_INTENSITY_MIN);
}

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
  const navigation = useNavigation();
  const insets = useSafeAreaInsets();
  const params = useLocalSearchParams<{ compare?: string; productId?: string; shadeId?: string; video?: string }>();
  const routeProductId = parseId(params.productId);
  const routeShadeId = parseId(params.shadeId);
  const fromVideo = parseFlag(params.video);
  const { t } = useI18n();
  const { height: windowHeight } = useWindowDimensions();
  const cameraConsent = useSettingsStore((s) => s.cameraConsent);
  const setCameraConsent = useSettingsStore((s) => s.setCameraConsent);
  const [permission, requestPermission] = useCameraPermissions();
  const cameraActive = useCameraActive();
  const routeSelection = useArRouteSelection(routeProductId, routeShadeId);
  const routeZone = routeSelection.product.data?.makeupZone ?? undefined;
  const compareParam = parseFlag(params.compare);
  const [status, setStatus] = useState<ArStatus>('loading');
  const [lightHint, setLightHint] = useState<LightHint | null>(null);
  const [skinTone, setSkinTone] = useState<SkinTone | null>(null);
  const [arKey, setArKey] = useState(0);
  const [swatchOnly, setSwatchOnly] = useState(false);
  const [compare, setCompare] = useState(compareParam);
  const [zone, setZone] = useState<MakeupZone>(routeZone ?? 'lip');
  // "Do it yourself": a step index and the zones put on so far. Display only; the store keeps the finished look.
  const [practice, setPractice] = useState<{ index: number; visited: MakeupZone[] } | null>(null);
  const [peek, setPeek] = useState(false);
  const [textureFilter, setTextureFilter] = useState<Texture | null>(null);
  const [familyFilter, setFamilyFilter] = useState<ColorFamily | null>(null);
  const [added, setAdded] = useState(false);
  const [recFor, setRecFor] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode>('direct');
  const [draft, setDraft] = useState('');
  const [isFullscreenAR, setIsFullscreenAR] = useState(false);

  // Follow new route params (a later "Try in AR" on the already-mounted tab) without an effect.
  const [seenParams, setSeenParams] = useState({ compare: compareParam, zone: routeZone });
  if (seenParams.compare !== compareParam || seenParams.zone !== routeZone) {
    setSeenParams({ compare: compareParam, zone: routeZone });
    if (compareParam) setCompare(true);
    if (routeZone) setZone(routeZone);
  }

  const {
    makeup,
    selections,
    activeLook,
    heroZones,
    stepOrder,
    modified,
    applyShade,
    patchGeometry,
    setIntensity,
    clearZone,
    revertZone,
    fit,
    endFit,
  } = useMakeupStore();
  const [blushTrackW, setBlushTrackW] = useState(0);
  const blushTrackWRef = useRef(0);
  const addMany = useCartStore((s) => s.addMany);
  const addToCart = useCartStore((s) => s.add);
  const products = useProducts();

  // Development: fall back to the bundled Olive Young + demo colors when the backend has no
  // try-on products, so AR can be tested in Expo Go without a seeded backend.
  const tryOnProducts = useMemo(
    () => withDevTryOnFallback((products.data ?? []).filter((p) => p.makeupZone), __DEV__),
    [products.data]
  );
  const zoneSwatches = useMemo(
    () =>
      tryOnProducts
        .filter((p) => p.makeupZone === zone)
        .flatMap((p) => p.shades.map((shade) => ({ product: p, shade }))),
    [tryOnProducts, zone]
  );
  // Filter chips: only textures / color families present in this zone; families for lips only.
  const textureOptions = useMemo(
    () =>
      zone === 'blush' || zone === 'eyeshadow' || zone === 'foundation'
        ? []
        : TEXTURES.filter((tx) => zoneSwatches.some(({ product }) => product.texture === tx)),
    [zoneSwatches, zone]
  );
  const familyOptions = useMemo(
    () =>
      zone === 'lip'
        ? COLOR_FAMILIES.filter((fm) => zoneSwatches.some(({ shade }) => colorFamily(shade.hex) === fm))
        : [],
    [zoneSwatches, zone]
  );
  // Foundation shades closest to the measured skin color, from the shades this tab offers (a color reference only).
  const foundMatches = useMemo(
    () =>
      zone === 'foundation' && skinTone && skinTone.conf >= MIN_TONE_CONF
        ? rankFoundationShades(skinTone, zoneSwatches).slice(0, 3)
        : [],
    [zone, skinTone, zoneSwatches]
  );
  const visibleSwatches = useMemo(
    () =>
      zoneSwatches.filter(
        ({ product, shade }) =>
          (!textureFilter || product.texture === textureFilter) &&
          (!familyFilter || colorFamily(shade.hex) === familyFilter)
      ),
    [zoneSwatches, textureFilter, familyFilter]
  );

  const showsDemo = useMemo(
    () =>
      Object.values(selections).some((s) =>
        tryOnProducts.find((p) => p.id === s?.productId)?.tags.includes(DEMO_TAG)
      ),
    [selections, tryOnProducts]
  );

  // A look opens on its first key zone (state adjusted while rendering, when the applied look changes).
  const [openedLookId, setOpenedLookId] = useState<string | null>(null);
  if ((activeLook?.id ?? null) !== openedLookId) {
    setOpenedLookId(activeLook?.id ?? null);
    if (activeLook) {
      const open = heroZones.find(isArPaintZone) ?? 'lip';
      setZone(open);
      setTextureFilter(null);
      setFamilyFilter(null);
    }
  }
  if (!isArPaintZone(zone)) setZone('lip');

  const seededLip = useRef(false);
  useEffect(() => {
    if (fit || seededLip.current || routeProductId || fromVideo) return;
    if (MAKEUP_ZONES.some((z) => makeup[z])) {
      seededLip.current = true;
      return;
    }
    const firstLip = tryOnProducts.find((p) => p.makeupZone === 'lip');
    if (!firstLip?.shades[0]) return;
    seededLip.current = true;
    applyShade(firstLip, firstLip.shades[0]);
  }, [routeProductId, tryOnProducts, makeup, applyShade, fit, fromVideo]);

  useFocusEffect(
    useCallback(() => {
      setStatus('loading');
      return () => {
        endFit();
      };
    }, [endFit])
  );

  useEffect(() => {
    if (!added) return;
    const timer = setTimeout(() => setAdded(false), 2400);
    return () => clearTimeout(timer);
  }, [added]);

  const isWeb = Platform.OS === 'web';
  const permissionGranted = isWeb || permission?.granted;
  const permissionBlocked = !isWeb && permission && !permission.granted && !permission.canAskAgain;
  const liveCamera =
    !!cameraConsent && !!permissionGranted && !permissionBlocked && !swatchOnly && status !== 'unavailable' && status !== 'denied';

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
  // A zone wearing a color that no chosen product has (a look color the shop lacks, a linked zone):
  // the nearest shade of the shop stands in for it, in the card below and in the set.
  const wornLines = useMemo(
    () =>
      Object.values(selections).flatMap((sel): LookLine[] => {
        const product = sel && tryOnProducts.find((p) => p.id === sel.productId);
        const shade = product ? product.shades.find((s) => s.id === sel.shadeId) : undefined;
        return product && shade ? [{ product, shade }] : [];
      }),
    [selections, tryOnProducts]
  );
  const gaps = useMemo(() => findColorGaps(makeup, wornLines, tryOnProducts), [makeup, wornLines, tryOnProducts]);
  const zoneGap = gaps.find((g) => g.zone === zone);
  const selectedLine = useMemo(() => {
    const sel = selections[zone];
    if (!sel) return null;
    const product = tryOnProducts.find((p) => p.id === sel.productId) ?? products.data?.find((p) => p.id === sel.productId);
    const shade = product?.shades.find((s) => s.id === sel.shadeId);
    return product && shade ? { product, shade } : null;
  }, [selections, zone, tryOnProducts, products.data]);
  const fitProduct =
    fit &&
    (tryOnProducts.find((p) => p.id === fit.productId) ?? products.data?.find((p) => p.id === fit.productId));
  const fitShade = fitProduct?.shades.find((s) => s.id === fit?.shadeId);
  const zoneHex = makeup[zone]?.hex;
  const recKey = zoneHex ? `${zone}:${zoneHex}` : null;
  const showRecs = recFor !== null && recFor === recKey;
  const recs = useMemo(() => {
    if (!showRecs || !zoneHex) return [];
    const sel = selections[zone];
    return recommendShades(zoneHex, zone, tryOnProducts, sel ?? null);
  }, [showRecs, zoneHex, zone, tryOnProducts, selections]);
  const onAddFit = () => {
    if (!fit) return;
    addToCart({ productId: fit.productId, shadeId: fit.shadeId });
    setAdded(true);
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
  };
  const onAddSelection = () => {
    if (added) {
      router.push('/cart');
      return;
    }
    addMany([
      ...selectionItems.map((s) => ({
        productId: s!.productId,
        shadeId: s!.shadeId,
        addedFromLookId: activeLook?.id,
      })),
    ]);
    setAdded(true);
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
  };

  const wing = makeup.eyeliner?.geometry;
  const practicing = !!practice && !!activeLook;
  const zonesOfSteps = useMemo(
    () => practiceZones(makeup, stepOrder).filter((z) => z === null || isArPaintZone(z)),
    [makeup, stepOrder]
  );
  const practiceIndex = practice ? Math.min(practice.index, zonesOfSteps.length - 1) : 0;
  const practiceZone = zonesOfSteps[practiceIndex] ?? null;
  const shownMakeup = useMemo(() => {
    const face = practicing && !peek && practice ? revealedMakeup(makeup, practice.visited) : makeup;
    return arPaintMakeup(face);
  }, [practicing, peek, practice, makeup]);
  const guide = useMemo(() => {
    const step = practicing && !peek ? practiceDrawStep(practiceZone) : null;
    return step ? guideMessage(step, wing) : null;
  }, [practicing, peek, practiceZone, wing]);
  const practiceSteps = useMemo(() => {
    const sentences = new Map(buildGuideSteps(makeup, stepOrder).map((g) => [g.zone, guideText(g, t)]));
    return zonesOfSteps.map((z) => ({
      key: z ?? 'eyebrow',
      zone: z,
      label: t(z === null ? 'ar.guide.eyebrow' : (`ar.zone.${z}` as TranslationKey)),
      text: z === null ? t('ar.guide.text.eyebrow') : (sentences.get(z) ?? ''),
    }));
  }, [makeup, stepOrder, zonesOfSteps, t]);
  const goToStep = (index: number) => {
    const next = Math.max(0, Math.min(index, zonesOfSteps.length - 1));
    setPractice((p) => (p ? { index: next, visited: visit(p.visited, zonesOfSteps[next] ?? null) } : p));
    setPeek(false);
  };
  const startPractice = () => {
    setCompare(false);
    setPeek(false);
    setPractice({ index: 0, visited: [] });
  };
  const exitPractice = () => {
    setPractice(null);
    setPeek(false);
  };

  const setMirrorMode = useCallback((next: boolean) => {
    LayoutAnimation.configureNext({
      duration: 260,
      update: { type: LayoutAnimation.Types.easeInEaseOut },
      create: { type: LayoutAnimation.Types.easeInEaseOut, property: LayoutAnimation.Properties.opacity },
      delete: { type: LayoutAnimation.Types.easeInEaseOut, property: LayoutAnimation.Properties.opacity },
    });
    setIsFullscreenAR(next);
  }, []);

  useEffect(() => {
    navigation.setOptions({ tabBarStyle: isFullscreenAR ? HIDDEN_TAB_BAR_STYLE : TAB_BAR_STYLE });
    return () => {
      navigation.setOptions({ tabBarStyle: TAB_BAR_STYLE });
    };
  }, [isFullscreenAR, navigation]);

  useEffect(() => {
    if (!isFullscreenAR) return;
    const sub = BackHandler.addEventListener('hardwareBackPress', () => {
      setMirrorMode(false);
      return true;
    });
    return () => sub.remove();
  }, [isFullscreenAR, setMirrorMode]);

  useFocusEffect(
    useCallback(() => {
      return () => {
        setIsFullscreenAR(false);
        navigation.setOptions({ tabBarStyle: TAB_BAR_STYLE });
      };
    }, [navigation])
  );

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
        <ArFaceView
          key={arKey}
          makeup={shownMakeup}
          compare={compare}
          guide={guide}
          onStatus={setStatus}
          onLightHint={setLightHint}
          onSkinTone={setSkinTone}
        />
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
        ) : status === 'tracking' && lightHint ? (
          <View style={styles.hintPill} pointerEvents="none">
            <Text style={styles.hintText}>
              {t(lightHint === 'blown' ? 'ar.lightHint.blown' : 'ar.lightHint.low')}
            </Text>
          </View>
        ) : null}
        {!isFullscreenAR ? (
          <View style={styles.liveBadge} pointerEvents="none">
            <View style={styles.liveDot} />
            <Text style={styles.liveText}>{t('ar.live')}</Text>
          </View>
        ) : null}
        {showsDemo && !isFullscreenAR ? (
          <View style={styles.demoBadge} pointerEvents="none">
            <Text style={styles.liveText}>{t('ar.demoColors')}</Text>
          </View>
        ) : null}
        {status !== 'no-face' && !isFullscreenAR ? (
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
    <SafeAreaView style={styles.screen} edges={isFullscreenAR ? [] : ['top']}>
      <View style={[styles.stage, isFullscreenAR && styles.stageMirror]}>
        {stage}
        {isFullscreenAR || router.canGoBack() ? (
          <Pressable
            onPress={() => (isFullscreenAR ? setMirrorMode(false) : router.back())}
            accessibilityRole="button"
            accessibilityLabel={t('common.back')}
            hitSlop={8}
            style={[styles.backBtn, isFullscreenAR && { top: Math.max(10, insets.top + 6) }]}>
            <Ionicons name="chevron-back" size={22} color={theme.colors.white} />
          </Pressable>
        ) : null}
        {isFullscreenAR ? (
          <Pressable
            onPress={() => setMirrorMode(false)}
            accessibilityRole="button"
            accessibilityLabel={t('ar.mirror.exit')}
            hitSlop={8}
            style={[styles.mirrorExpandBtn, { bottom: Math.max(16, insets.bottom + 12) }]}>
            <Ionicons name="chevron-up" size={22} color={theme.colors.white} />
          </Pressable>
        ) : null}
      </View>

      {isFullscreenAR ? null : (
      <View style={styles.panel}>
        {liveCamera ? (
          <Pressable
            onPress={() => setMirrorMode(true)}
            accessibilityRole="button"
            accessibilityLabel={t('ar.mirror.enter')}
            hitSlop={8}
            style={styles.mirrorFoldBtn}>
            <Ionicons name="chevron-down" size={22} color={theme.colors.inkMuted} />
          </Pressable>
        ) : null}
        {practicing || fit ? null : (
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
        )}

        {activeLook && !fit ? (
          <Text style={styles.lookBanner} numberOfLines={1}>
            {t(modified.length > 0 ? 'ar.lookModified' : 'ar.lookApplied', { title: activeLook.title })}
          </Text>
        ) : null}
        {fromVideo ? <Text style={styles.warnBanner}>{t('videoAr.notice')}</Text> : null}
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

        {fit ? (
          <View style={styles.fitPanel}>
            <Text style={styles.matchTitle}>{t('ar.fitTitle')}</Text>
            {fitProduct && fitShade ? (
              <>
                <Text style={styles.matchName} numberOfLines={2}>
                  {fitProduct.brand} {fitProduct.name} · {fitShade.name}
                </Text>
                <Text style={styles.matchNote}>{formatKRW(fitProduct.priceKRW)}</Text>
              </>
            ) : (
              <Text style={styles.matchNote}>{t('ar.fitUnknown')}</Text>
            )}
            <View style={styles.actions}>
              <Button
                label={added ? t('ar.addedSelection') : t('ar.addThisProduct')}
                icon={added ? 'checkmark' : 'cart-outline'}
                onPress={onAddFit}
                style={{ flex: 1 }}
              />
              <Button
                label={t('ar.backToProduct')}
                variant="secondary"
                icon="arrow-back-outline"
                onPress={() => router.push({ pathname: '/product/[id]', params: { id: fit.productId, shade: fit.shadeId } })}
                style={{ flex: 1 }}
              />
            </View>
          </View>
        ) : practicing ? (
          <PracticePanel
            title={t('ar.practice.title')}
            intro={t('ar.practice.intro')}
            steps={practiceSteps.map((step, i) => ({
              key: step.key,
              label: step.label,
              done: step.zone === null ? i < practiceIndex : !!practice?.visited.includes(step.zone),
            }))}
            activeIndex={practiceIndex}
            text={practiceSteps[practiceIndex]?.text ?? ''}
            peeking={peek}
            labels={{
              prev: t('ar.practice.prev'),
              next: t('ar.practice.next'),
              finish: t('ar.practice.finish'),
              peek: t('ar.practice.peek'),
              peekOff: t('ar.practice.peekOff'),
              exit: t('ar.practice.exit'),
            }}
            onPick={goToStep}
            onPrev={() => goToStep(practiceIndex - 1)}
            onNext={() => (practiceIndex >= practiceSteps.length - 1 ? exitPractice() : goToStep(practiceIndex + 1))}
            onPeek={() => setPeek((v) => !v)}
            onExit={exitPractice}
          />
        ) : mode === 'chat' ? (
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
          <ScrollView
            nestedScrollEnabled
            keyboardShouldPersistTaps="handled"
            style={[styles.exploreScroll, { maxHeight: windowHeight * 0.38 }]}
            contentContainerStyle={styles.exploreContent}
            showsVerticalScrollIndicator>
            <ScrollView
              horizontal
              nestedScrollEnabled
              showsHorizontalScrollIndicator={false}
              style={styles.zoneScroll}
              contentContainerStyle={styles.zoneRow}>
              {AR_PAINT_ZONES.map((z) => (
                <Pressable
                  key={z}
                  onPress={() => {
                    setZone(z);
                    setTextureFilter(null);
                    setFamilyFilter(null);
                  }}
                  accessibilityRole="tab"
                  accessibilityState={{ selected: zone === z }}
                  style={[styles.zoneTab, zone === z && styles.zoneTabActive]}>
                  <View style={[styles.zoneDot, { backgroundColor: makeup[z]?.hex ?? theme.colors.border }]} />
                  <Text style={[styles.zoneText, zone === z && styles.zoneTextActive]}>
                    {t(`ar.zone.${z}` as TranslationKey)}
                  </Text>
                  {heroZones.includes(z) ? (
                    <Ionicons name="star" size={11} color={theme.colors.rose} accessibilityLabel={t('ar.hero')} />
                  ) : null}
                  {modified.includes(z) ? <Ionicons name="create-outline" size={12} color={theme.colors.inkMuted} /> : null}
                </Pressable>
              ))}
            </ScrollView>

            {products.isError ? (
              <View style={styles.inlineRow}>
                <Text style={styles.noProducts}>{t('common.errorTitle')}</Text>
                <Button label={t('common.retry')} variant="ghost" compact onPress={() => products.refetch()} />
              </View>
            ) : zoneSwatches.length === 0 && !products.isPending ? (
              <Text style={styles.noProducts}>{t('ar.noProducts')}</Text>
            ) : null}
            {textureOptions.length + familyOptions.length > 1 ? (
              <ScrollView
                horizontal
                nestedScrollEnabled
                showsHorizontalScrollIndicator={false}
                style={styles.hScroll}
                contentContainerStyle={styles.filters}>
                <Chip
                  label={t('ar.filter.all')}
                  selected={!textureFilter && !familyFilter}
                  onPress={() => {
                    setTextureFilter(null);
                    setFamilyFilter(null);
                  }}
                />
                {textureOptions.map((tx) => (
                  <Chip
                    key={tx}
                    label={t(`ar.texture.${tx}` as TranslationKey)}
                    selected={textureFilter === tx}
                    onPress={() => setTextureFilter(textureFilter === tx ? null : tx)}
                  />
                ))}
                {familyOptions.length ? <View style={styles.filterDivider} /> : null}
                {familyOptions.map((fm) => (
                  <Chip
                    key={fm}
                    label={t(`ar.family.${fm}` as TranslationKey)}
                    selected={familyFilter === fm}
                    onPress={() => setFamilyFilter(familyFilter === fm ? null : fm)}
                  />
                ))}
              </ScrollView>
            ) : null}
            {zoneSwatches.length > 0 && visibleSwatches.length === 0 ? (
              <Text style={styles.noProducts}>{t('ar.filter.empty')}</Text>
            ) : null}
            {zoneGap && !selectedLine ? (
              <View style={styles.matchCard}>
                <Text style={styles.matchTitle}>{t('ar.match.title')}</Text>
                {zoneGap.kind === 'nearest' ? (
                  <>
                    <Text style={styles.matchName} numberOfLines={2}>
                      {zoneGap.nearest.product.brand} {zoneGap.nearest.product.name} · {zoneGap.nearest.shade.name}
                    </Text>
                    <Text style={styles.matchNote}>
                      {zoneGap.amount === null
                        ? t('looks.color.asIs')
                        : zoneGap.amount.dir === 'thicker'
                          ? t('looks.color.thicker', { n: zoneGap.amount.layers })
                          : t('looks.color.thinner')}
                    </Text>
                    <Chip
                      label={t('ar.match.use')}
                      onPress={() => applyShade(zoneGap.nearest.product, zoneGap.nearest.shade)}
                    />
                  </>
                ) : (
                  <Text style={styles.matchNote}>{t('ar.match.none')}</Text>
                )}
              </View>
            ) : null}
            {modified.includes(zone) ? (
              <View style={styles.revertRow}>
                <Chip label={t('ar.revertZone')} onPress={() => revertZone(zone)} />
              </View>
            ) : null}
            <ScrollView
              horizontal
              nestedScrollEnabled
              showsHorizontalScrollIndicator={false}
              style={styles.hScroll}
              contentContainerStyle={styles.swatches}>
              {visibleSwatches.map(({ product, shade }) => {
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
              <Chip label={t('ar.off')} selected={!makeup[zone]} onPress={() => clearZone(zone)} />
            </View>
            {zone === 'foundation' && makeup.foundation ? (
              <View style={styles.foundBox}>
                <Text style={styles.foundTitle}>{t('ar.found.coverage')}</Text>
                <CoverageBar
                  value={makeup.foundation.intensity}
                  labels={{ title: t('ar.found.coverage'), low: t('ar.found.sheer'), high: t('ar.found.full') }}
                  onChange={(v) => setIntensity('foundation', v)}
                />
                <Text style={styles.foundNote}>{t('ar.found.coverageNote')}</Text>
              </View>
            ) : null}
            {zone === 'foundation' && zoneSwatches.length > 0 ? (
              <View style={styles.foundBox}>
                <Text style={styles.foundTitle}>{t('ar.found.suggest')}</Text>
                {foundMatches.length === 0 ? (
                  <Text style={styles.foundNote}>{t('ar.found.suggestWait')}</Text>
                ) : (
                  <View style={styles.foundChips}>
                    {foundMatches.map((m, i) => (
                      <Chip
                        key={`${m.product.id}-${m.shade.id}`}
                        label={`${i === 0 ? '★ ' : ''}${m.shade.name} · ${m.product.name} · ΔE ${m.deltaE.toFixed(0)}`}
                        selected={
                          selections.foundation?.productId === m.product.id && selections.foundation?.shadeId === m.shade.id
                        }
                        onPress={() => applyShade(m.product, m.shade)}
                      />
                    ))}
                  </View>
                )}
                {foundMatches[0] ? (
                  <Text style={styles.foundNote}>
                    {t(
                      foundMatches[0].deltaL > 3
                        ? 'ar.found.lighter'
                        : foundMatches[0].deltaL < -3
                          ? 'ar.found.darker'
                          : 'ar.found.close',
                      { d: foundMatches[0].deltaE.toFixed(0) }
                    )}
                  </Text>
                ) : null}
                <Text style={styles.foundNote}>{t('ar.found.suggestNote')}</Text>
              </View>
            ) : null}
            {zone === 'blush' && makeup.blush ? (
              <View style={styles.blushLevel}>
                <Text style={styles.blushLevelLabel}>{t('ar.light')}</Text>
                <View
                  accessibilityRole="adjustable"
                  accessibilityLabel={t('ar.intensity')}
                  accessibilityValue={{
                    min: Math.round(BLUSH_INTENSITY_MIN * 100),
                    max: 100,
                    now: Math.round(makeup.blush.intensity * 100),
                  }}
                  style={styles.blushTrackHit}
                  onLayout={(e) => {
                    const w = e.nativeEvent.layout.width;
                    blushTrackWRef.current = w;
                    setBlushTrackW(w);
                  }}
                  onStartShouldSetResponder={() => true}
                  onMoveShouldSetResponder={() => true}
                  onResponderGrant={(e: GestureResponderEvent) =>
                    setIntensity('blush', blushIntensityFromX(e.nativeEvent.locationX, blushTrackWRef.current))
                  }
                  onResponderMove={(e: GestureResponderEvent) =>
                    setIntensity('blush', blushIntensityFromX(e.nativeEvent.locationX, blushTrackWRef.current))
                  }>
                  <LinearGradient
                    colors={[mixHexTowardWhite(makeup.blush.hex, 0.72), makeup.blush.hex]}
                    start={{ x: 0, y: 0.5 }}
                    end={{ x: 1, y: 0.5 }}
                    style={styles.blushTrack}
                  />
                  <View
                    pointerEvents="none"
                    style={[
                      styles.blushKnob,
                      {
                        left:
                          blushTrackW <= 0
                            ? 0
                            : Math.min(
                                1,
                                Math.max(0, (makeup.blush.intensity - BLUSH_INTENSITY_MIN) / (1 - BLUSH_INTENSITY_MIN))
                              ) * Math.max(0, blushTrackW - BLUSH_KNOB),
                      },
                    ]}
                  />
                </View>
                <Text style={styles.blushLevelLabel}>{t('ar.bold')}</Text>
              </View>
            ) : null}
            {zone === 'eyeshadow' && makeup.eyeshadow ? (
              <ScrollView
                horizontal
                nestedScrollEnabled
                showsHorizontalScrollIndicator={false}
                style={styles.hScroll}
                contentContainerStyle={styles.filters}>
                {SHADOW_FINISH_IDS.map((id) => (
                  <Chip
                    key={id}
                    label={t((id === 'glitter' ? 'ar.shadow.glitter' : `ar.texture.${id}`) as TranslationKey)}
                    selected={shadowFinishOf(makeup.eyeshadow) === id}
                    onPress={() => makeup.eyeshadow && patchGeometry('eyeshadow', { shadowFinish: id })}
                  />
                ))}
              </ScrollView>
            ) : null}
            {zone === 'eyeliner' ? (
              <ScrollView
                horizontal
                nestedScrollEnabled
                showsHorizontalScrollIndicator={false}
                style={styles.hScroll}
                contentContainerStyle={styles.filters}>
                {LINER_LOOK_IDS.map((id) => (
                  <Chip
                    key={id}
                    label={t(`ar.liner.${id}` as TranslationKey)}
                    selected={matchingLinerLook(makeup.eyeliner?.geometry) === id}
                    onPress={() => makeup.eyeliner && patchGeometry('eyeliner', LINER_LOOKS[id])}
                  />
                ))}
              </ScrollView>
            ) : null}
            <View style={styles.actions}>
              <Button
                label={t('ar.recommendColor')}
                icon="pricetag-outline"
                disabled={!zoneHex}
                onPress={() => recKey && setRecFor(recKey)}
                style={{ flex: 1 }}
              />
              <Button
                label={added ? t('looks.viewCart') : t('ar.addSelection')}
                variant="secondary"
                icon={added ? 'checkmark' : 'cart-outline'}
                disabled={selectionItems.length === 0}
                onPress={onAddSelection}
                style={{ flex: 1 }}
              />
            </View>
            {showRecs ? (
              recs.length === 0 ? (
                <Text style={styles.noProducts}>{t('ar.recommendEmpty')}</Text>
              ) : (
                recs.map((row) => (
                  <Pressable
                    key={`${row.product.id}-${row.shade.id}`}
                    onPress={() =>
                      router.push({
                        pathname: '/product/[id]',
                        params: { id: row.product.id, shade: row.shade.id },
                      })
                    }
                    accessibilityRole="button"
                    style={styles.matchCard}>
                    <Text style={styles.matchTitle}>{t('ar.recommendColor')}</Text>
                    <Text style={styles.matchName} numberOfLines={2}>
                      {row.product.brand} {row.product.name} · {row.shade.name}
                    </Text>
                    <Text style={styles.matchNote}>{formatKRW(row.product.priceKRW)}</Text>
                  </Pressable>
                ))
              )
            ) : null}
            <View style={styles.actions}>
              <Button
                label={t('ar.similar')}
                variant="secondary"
                icon="color-filter-outline"
                disabled={!zoneSelection}
                onPress={openRecommendations}
              />
            </View>
            {activeLook ? (
              <Button
                label={t('ar.practice.start')}
                icon="brush-outline"
                variant="secondary"
                onPress={startPractice}
                style={styles.practiceBtn}
              />
            ) : null}
          </ScrollView>
        )}
        <Text style={styles.disclaimer}>{t('ar.disclaimer')}</Text>
      </View>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.ink },
  stage: { flex: 1, margin: 10, marginBottom: 0, borderRadius: theme.radius.lg, overflow: 'hidden', backgroundColor: theme.colors.black },
  stageMirror: { margin: 0, borderRadius: 0 },
  mirrorFoldBtn: {
    alignSelf: 'center',
    minWidth: theme.hitTarget,
    minHeight: 32,
    marginTop: -6,
    marginBottom: 2,
    alignItems: 'center',
    justifyContent: 'center',
  },
  mirrorExpandBtn: {
    position: 'absolute',
    alignSelf: 'center',
    width: theme.hitTarget,
    height: theme.hitTarget,
    borderRadius: theme.hitTarget / 2,
    backgroundColor: theme.colors.overlay,
    alignItems: 'center',
    justifyContent: 'center',
  },
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
  hintPill: { position: 'absolute', bottom: 64, alignSelf: 'center', backgroundColor: theme.colors.overlay, paddingHorizontal: 14, paddingVertical: 8, borderRadius: theme.radius.pill },
  hintText: { color: theme.colors.white, fontSize: theme.font.small, fontWeight: '600', textAlign: 'center' },
  liveBadge: { position: 'absolute', top: 12, left: 12, flexDirection: 'row', alignItems: 'center', gap: 6, backgroundColor: theme.colors.overlay, paddingHorizontal: 10, paddingVertical: 5, borderRadius: theme.radius.pill },
  demoBadge: { position: 'absolute', top: 44, left: 12, backgroundColor: theme.colors.overlay, paddingHorizontal: 10, paddingVertical: 5, borderRadius: theme.radius.pill },
  liveDot: { width: 7, height: 7, borderRadius: 4, backgroundColor: '#4ADE80' },
  liveText: { color: theme.colors.white, fontSize: 11, fontWeight: '600' },
  compareBtn: { position: 'absolute', bottom: 14, alignSelf: 'center', flexDirection: 'row', alignItems: 'center', gap: 6, backgroundColor: theme.colors.overlay, paddingHorizontal: 14, minHeight: 40, borderRadius: theme.radius.pill },
  compareText: { color: theme.colors.white, fontSize: theme.font.small, fontWeight: '600' },
  compareLabel: { position: 'absolute', top: 44, paddingHorizontal: 9, paddingVertical: 5, borderRadius: theme.radius.pill, backgroundColor: theme.colors.overlay },
  beforeLabel: { left: 12 },
  afterLabel: { right: 12 },
  compareLabelText: { color: theme.colors.white, fontSize: 11, fontWeight: '800' },
  splitLine: { position: 'absolute', top: 0, bottom: 0, left: '50%', width: 2, marginLeft: -1, backgroundColor: 'rgba(255,255,255,0.9)' },
  warnBanner: { marginHorizontal: 16, fontSize: 12, fontWeight: '600', color: theme.colors.warning },
  practiceBtn: { marginHorizontal: 16 },
  matchCard: { marginHorizontal: 16, padding: 10, gap: 4, alignItems: 'flex-start', borderRadius: theme.radius.md, backgroundColor: theme.colors.roseSoft },
  matchTitle: { fontSize: 11, fontWeight: '800', color: theme.colors.roseDark },
  matchName: { fontSize: theme.font.small, fontWeight: '700', color: theme.colors.ink },
  matchNote: { fontSize: 12, color: theme.colors.inkMuted, lineHeight: 17 },
  fitPanel: { marginHorizontal: 16, padding: 10, gap: 8, alignItems: 'flex-start', borderRadius: theme.radius.md, backgroundColor: theme.colors.roseSoft },
  revertRow: { marginHorizontal: 16, alignItems: 'flex-start' },
  panel: { flexGrow: 0, backgroundColor: theme.colors.surface, borderTopLeftRadius: theme.radius.lg, borderTopRightRadius: theme.radius.lg, marginTop: 10, paddingTop: 14, paddingBottom: 12, gap: 10 },
  exploreScroll: { flexGrow: 0 },
  exploreContent: { gap: 10, paddingBottom: 4 },
  hScroll: { flexGrow: 0 },
  lookBanner: { marginHorizontal: 16, fontSize: 12, fontWeight: '700', color: theme.colors.rose },
  zoneScroll: { flexGrow: 0, marginHorizontal: 16, backgroundColor: theme.colors.surfaceAlt, borderRadius: theme.radius.md },
  zoneRow: { padding: 3 },
  zoneTab: { flexDirection: 'row', paddingHorizontal: 14, alignItems: 'center', justifyContent: 'center', gap: 6, paddingVertical: 8, borderRadius: 10 },
  zoneTabActive: { backgroundColor: theme.colors.card, ...theme.shadow },
  zoneDot: { width: 10, height: 10, borderRadius: 5 },
  zoneText: { fontSize: theme.font.small, fontWeight: '600', color: theme.colors.inkMuted },
  zoneTextActive: { color: theme.colors.ink },
  filters: { gap: 8, paddingHorizontal: 16, paddingBottom: 10, alignItems: 'center' },
  filterDivider: { width: 1, height: 20, backgroundColor: theme.colors.border, marginHorizontal: 2 },
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
  foundBox: { marginHorizontal: 16, gap: 6 },
  foundTitle: { fontSize: 12, fontWeight: '800', color: theme.colors.ink },
  foundNote: { fontSize: 11, lineHeight: 16, color: theme.colors.inkMuted },
  foundChips: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  blushLevel: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: 16 },
  blushLevelLabel: { fontSize: 11, fontWeight: '700', color: theme.colors.inkMuted },
  blushTrackHit: { flex: 1, height: 28, justifyContent: 'center' },
  blushTrack: { height: 10, borderRadius: 5, borderWidth: 1, borderColor: 'rgba(0,0,0,0.08)' },
  blushKnob: {
    position: 'absolute',
    top: 4,
    width: BLUSH_KNOB,
    height: BLUSH_KNOB,
    borderRadius: BLUSH_KNOB / 2,
    backgroundColor: theme.colors.white,
    borderWidth: 1,
    borderColor: 'rgba(0,0,0,0.12)',
    ...theme.shadow,
  },
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
