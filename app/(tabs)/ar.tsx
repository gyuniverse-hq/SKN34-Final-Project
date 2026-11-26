import Ionicons from '@expo/vector-icons/Ionicons';
import { uuid } from 'expo';
import { useCameraPermissions } from 'expo-camera';
import * as Haptics from 'expo-haptics';
import { LinearGradient } from 'expo-linear-gradient';
import * as WebBrowser from 'expo-web-browser';
import { useFirstArExit } from '@/hooks/useFirstArExit';
import { useFocusEffect, useLocalSearchParams, useNavigation, useRouter } from 'expo-router';
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import {
  ActivityIndicator,
  Alert,
  AppState,
  BackHandler,
  LayoutAnimation,
  KeyboardAvoidingView,
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
} from 'react-native';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import { ArFaceView, type PoseHint } from '@/components/ar/ArFaceView';
import { ArSheet } from '@/components/ar/ArSheet';
import { ArZoneWheel, zoneWheelRadius } from '@/components/ar/ArZoneWheel';
import { IntensityRail } from '@/components/ar/IntensityRail';
import { TextureSelect } from '@/components/ar/TextureSelect';
import { NEARBY_DIRECTIONS, type ColorSwatch } from '@/lib/nearbyColors';
import { OpenArcPalette } from '@/components/ar/OpenArcPalette';
import { CoverageBar } from '@/components/ar/CoverageBar';
import { NearbyExplorer } from '@/components/ar/NearbyExplorer';
import { PracticePanel } from '@/components/ar/PracticePanel';
import type { ArStatus } from '@/components/ar/faceTrackerHtml';
import { SwatchFallback } from '@/components/ar/SwatchFallback';
import { Button } from '@/components/ui/Button';
import { Chip } from '@/components/ui/Chip';
import { ProductImage } from '@/components/ui/ProductImage';
import { DEMO_TAG } from '@/constants/demo';
import { TAB_BAR_STYLE, theme } from '@/constants/theme';
import {
  effectiveHighlighterAreas,
  HIGHLIGHT_FACES,
  HIGHLIGHTER_AREAS,
  highlighterAreaPatch,
  highlighterFaceOf,
} from '@/lib/arFacePalette';
import { HIGHLIGHTER_STYLE_IDS, type FaceFitHint, type FaceFitStatus, type FaceShape } from '@/lib/faceFit';
import { COLOR_FAMILIES, colorFamily, type ColorFamily } from '@/lib/colorFamily';
import { reject, result, type ControlOperation, type ControlScreen } from '@/lib/arControl';
import { catalogMatches, makeupControls, shadeInfo, worn } from '@/lib/arMakeupControls';
import { subscribeArIdentityChange } from '@/lib/api';
import { isSafeExternalUrl } from '@/lib/externalLink';
import { formatKRW } from '@/lib/format';
import { LINER_LOOK_IDS, LINER_LOOKS, matchingLinerLook } from '@/lib/linerLooks';
import { SHADOW_FINISH_IDS, glitterTraitsOf, shadowFinishOf } from '@/lib/shadowFinishes';
import { findColorGaps, recommendShades, type LookLine } from '@/lib/colorGaps';
import { guideMessage } from '@/lib/drawGuide';
import { buildGuideSteps, guideText } from '@/lib/lookGuide';
import { practiceDrawStep, practiceZones, revealedMakeup, visit } from '@/lib/practice';
import { useArRecording } from '@/hooks/useArRecording';
import { useArRouteSelection } from '@/hooks/useArRouteSelection';
import { usableShadeTone } from '@/lib/arShadePreference';
import { useNearbyExploration } from '@/hooks/useNearbyExploration';
import { useArHistory } from '@/hooks/useArHistory';
import { noteArFailure } from '@/lib/arHistory';
import { useArCommand } from '@/hooks/useArCommand';
import { integratedVoiceModel, useArVoiceSession } from '@/hooks/useArVoiceSession';
import { useArVoice } from '@/hooks/useArVoice';
import { arVoiceKeywords } from '@/lib/arVoiceContext';
import { useArEnvMessage } from '@/hooks/useArEnvMessage';
import { MIN_TONE_CONF, rankFoundationShades, type SkinTone } from '@/lib/foundationMatch';
import { ENV_MESSAGE_KEY, type EnvState } from '@/lib/arEnv';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import { useTryOnProducts } from '@/lib/queries';
import { demoLookTitleKey, isDemoLook } from '@/lib/demoLookAr';
import { LOOK_STRENGTH_DEFAULT, LOOK_STRENGTH_MAX, LOOK_STRENGTH_MIN, videoLookMakeup } from '@/lib/videoLookMakeup';
import { parseFlag, parseId, productHref, recommendationsHref } from '@/lib/routes';
import { useCartStore } from '@/store/cartStore';
import { isLipBaseCare, LIP_TEXTURE_CHIPS, lipCareKind, lipTextureChip } from '@/lib/lipCare';
import { AR_PAINT_ZONES, arPaintMakeup, isArPaintZone, useMakeupStore } from '@/store/makeupStore';
import { useMemberCameraConsent } from '@/hooks/useMemberCameraConsent';
import { useSettingsStore } from '@/store/settingsStore';
import type { HighlightFace, MakeupZone, Product, Shade, Texture } from '@/types';

type Mode = 'direct' | 'chat';
type RecommendationKind = 'foundation_match' | 'look_gap' | 'similar_shades' | 'personalized';
interface RecommendationList {
  kind: RecommendationKind;
  scope: string;
  catalog: readonly Product[];
  items: readonly ColorSwatch[];
}

const DETAIL_CONTROL_CHOICES = new Set([
  'navigate/cart', 'navigate/back',
  'set_view/mirror/on', 'set_view/mirror/off', 'retry_catalog',
]);

const VoiceSessionView = lazy(() => import('@/components/ar/VoiceSessionView').then(module => ({ default: module.VoiceSessionView })));
const HIDDEN_TAB_BAR_STYLE = { ...TAB_BAR_STYLE, display: 'none' as const, height: 0 };
// Both modes share the palette (112) + category hub (88) footprint below the product row.
const AR_DOCK_BODY_HEIGHT = 200;
const AR_PRODUCT_ROW_HEIGHT = 44;

if (Platform.OS === 'android' && UIManager.setLayoutAnimationEnabledExperimental) {
  UIManager.setLayoutAnimationEnabledExperimental(true);
}

const CHAT_EXAMPLES = [
  { label: 'ar.chatSuggestion.lip', request: 'ar.chatExample1' },
  { label: 'ar.chatSuggestion.blush', request: 'ar.chatExample2' },
  { label: 'ar.chatSuggestion.coral', request: 'ar.chatExample3' },
] as const;
const AR_COMMAND_STATUS = {
  interpreting: 'ar.command.interpreting',
  proposed: 'ar.command.proposed',
  applying: 'ar.command.applying',
  applied: 'ar.command.applied',
  no_change: 'ar.command.noChange',
  clarification: 'ar.command.clarification',
  rejected: 'ar.command.rejected',
  failed: 'ar.command.failed',
  unknown: 'ar.command.unknown',
} as const;
const AR_RESTORE_STATUS = {
  pending: 'ar.command.restorePending',
  confirmed: 'ar.command.restoreConfirmed',
  failed: 'ar.command.restoreFailed',
  unknown: 'ar.command.restoreUnknown',
  unavailable: 'ar.command.restoreUnavailable',
} as const;
const TEXTURES: Texture[] = ['matte', 'velvet', 'cream', 'satin', 'sheer', 'glossy', 'shimmer'];
const BLUSH_INTENSITY_MIN = 0.15;

function useCameraActive() {
  const [focused, setFocused] = useState(false);
  const [appState, setAppState] = useState(AppState.currentState);
  useFocusEffect(
    useCallback(() => {
      const { fit, careSelection, selections } = useMakeupStore.getState();
      const fitZone = fit && (careSelection?.productId === fit.productId && careSelection.shadeId === fit.shadeId
        ? 'lipCare' : AR_PAINT_ZONES.find(z => selections[z]?.productId === fit.productId && selections[z]?.shadeId === fit.shadeId));
      useMakeupStore.setState({ tryOnHistory: fit && fitZone ? [{ ...fit, zone: fitZone }] : [] });
      setFocused(true);
      return () => {
        useMakeupStore.setState({ tryOnHistory: null });
        setFocused(false);
      };
    }, [])
  );
  useEffect(() => {
    const sub = AppState.addEventListener('change', setAppState);
    return () => sub.remove();
  }, []);
  // The iOS microphone permission sheet briefly sets the app to inactive.
  return { cameraActive: focused && appState === 'active', voiceActive: focused && appState !== 'background' };
}

/** `/ar?productId&shadeId&compare=1`: opened from home, a look, or a product ("Try in AR"). */
export default function ArTryOnScreen() {
  const router = useRouter();
  const navigation = useNavigation();
  const exitAr = useFirstArExit();
  const insets = useSafeAreaInsets();
  const params = useLocalSearchParams<{ compare?: string; productId?: string; shadeId?: string; video?: string }>();
  const routeProductId = parseId(params.productId);
  const routeShadeId = parseId(params.shadeId);
  const fromVideo = parseFlag(params.video);
  const { t, language } = useI18n();
  const { height: windowHeight, width: windowWidth } = useWindowDimensions();
  const dockBottom = Math.max(24, insets.bottom);
  const cameraChoice = useMemberCameraConsent();
  const guestCameraConsent = useSettingsStore((s) => s.cameraConsent);
  const cameraConsent = cameraChoice.member ? cameraChoice.granted : guestCameraConsent;
  const setCameraConsent = useSettingsStore((s) => s.setCameraConsent);
  const [permission, requestPermission] = useCameraPermissions();
  const { cameraActive, voiceActive } = useCameraActive();
  const routeSelection = useArRouteSelection(routeProductId, routeShadeId);
  const routeZone = routeSelection.product.data?.makeupZone ?? undefined;
  const compareParam = parseFlag(params.compare);
  const [status, setStatus] = useState<ArStatus>('loading');
  const [poseHint, setPoseHint] = useState<PoseHint | null>(null);
  // 11-19: one shooting-environment message at a time (lib/arEnv display rules; the page sends a settled state).
  const [arEnv, setArEnv] = useState<EnvState | null>(null);
  const envMessage = useArEnvMessage(status === 'tracking' ? arEnv : null, status === 'no-face');
  const [skinTone, setSkinTone] = useState<SkinTone | null>(null);
  const [faceFitHints, setFaceFitHints] = useState<FaceFitHint[] | null>(null);
  const [faceShape, setFaceShape] = useState<FaceShape | null>(null);
  const [faceFitStatus, setFaceFitStatus] = useState<FaceFitStatus>('default');
  const onFaceFit = useCallback((hints: FaceFitHint[], shape: FaceShape | null) => {
    setFaceFitHints(hints);
    setFaceShape(shape);
  }, []);
  const onFaceFitStatus = useCallback((status: FaceFitStatus) => {
    setFaceFitStatus(status);
    // A new measurement (someone else in front, or no result yet): the old shape no longer applies.
    if (status !== 'personalized') setFaceShape(null);
  }, []);
  // One name per face shape in both panels (shading and highlighter); gaunt is a highlighter-only pick.
  const hlFaceName = (face: HighlightFace) =>
    t((face === 'gaunt' ? 'ar.hlFace.name.gaunt' : `ar.faceShape.name.${face}`) as TranslationKey);
  const [arKey, setArKey] = useState(0);
  const [swatchOnly, setSwatchOnly] = useState(false);
  const [compare, setCompare] = useState(compareParam);
  const [zone, setZone] = useState<MakeupZone>(routeZone ?? 'lip');
  // "Do it yourself": a step index and the zones put on so far. Display only; the store keeps the finished look.
  const [practice, setPractice] = useState<{ index: number; visited: MakeupZone[] } | null>(null);
  const [peek, setPeek] = useState(false);
  const [textureFilter, setTextureFilter] = useState<Texture | null>(null);
  const [familyFilter, setFamilyFilter] = useState<ColorFamily | null>(null);
  // Lip tab: null = colour lips, otherwise the 립케어 chip is open on 'all' / 'oil' / 'balm'.
  const [careChip, setCareChip] = useState<'all' | 'oil' | 'balm' | null>(null);
  const [added, setAdded] = useState(false);
  const [recFor, setRecFor] = useState<string | null>(null);
  const [recommendationList, setRecommendationList] = useState<RecommendationList | null>(null);
  const [mode, setMode] = useState<Mode>('direct');
  const [focusedMode, setFocusedMode] = useState<Mode | null>(null);
  const [sheet, setSheet] = useState<'tools' | 'product' | 'info' | null>(null);
  const [recommendHint, setRecommendHint] = useState<'new' | 'visible' | 'done'>('new');
  useEffect(() => {
    if (recommendHint !== 'visible') return;
    const timer = setTimeout(() => setRecommendHint('done'), 6500);
    return () => clearTimeout(timer);
  }, [recommendHint]);
  const [zoneMenuOpen, setZoneMenuOpen] = useState(false);
  const [addedShade, setAddedShade] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [testKeyboard, setTestKeyboard] = useState(false);
  function switchMode(next: Mode) {
    if (next !== mode) setTestKeyboard(false);
    setMode(next);
  }
  const [sendingChat, setSendingChat] = useState(false);
  const [chatRequest, setChatRequest] = useState('');
  const clearConversation = useCallback(() => {
    setTestKeyboard(false);
    setRecommendationList(null);
    setChatRequest('');
    setDraft('');
  }, []);
  useEffect(() => subscribeArIdentityChange(clearConversation), [clearConversation]);
  const [isFullscreenAR, setIsFullscreenAR] = useState(false);
  useEffect(() => {
    if (!addedShade) return;
    const timer = setTimeout(() => setAddedShade(null), 2200);
    return () => clearTimeout(timer);
  }, [addedShade]);

  // Follow new route params (a later "Try in AR" on the already-mounted tab) without an effect.
  const [seenParams, setSeenParams] = useState({ compare: compareParam, zone: routeZone });
  if (seenParams.compare !== compareParam || seenParams.zone !== routeZone) {
    setSeenParams({ compare: compareParam, zone: routeZone });
    if (compareParam) setCompare(true);
    if (routeZone) {
      setZone(routeZone);
      if (seenParams.zone !== routeZone) {
        setTextureFilter(null);
        setFamilyFilter(null);
      }
    }
  }

  const {
    makeup,
    selections,
    careSelection,
    tryOnHistory,
    activeLook,
    heroZones,
    stepOrder,
    modified,
    applyShade,
    clearZone,
    clearLipCare,
    patchGeometry,
    setShadowPoint,
    setIntensity,
    revertZone,
    fit,
    endFit,
    clearLookMascara,
  } = useMakeupStore();
  // Eyeshadow point colour mode (11-17): while on, a swatch tap sets the second shade at the outer V / crease.
  const [shadowPointMode, setShadowPointMode] = useState(false);
  const shadowPointing = shadowPointMode && zone === 'eyeshadow' && !!makeup.eyeshadow;
  const addMany = useCartStore((s) => s.addMany);
  const addToCart = useCartStore((s) => s.add);
  const cartCount = useCartStore((s) => s.items.reduce((sum, item) => sum + item.quantity, 0));
  // Development only (AR_SPEC 11-02): record the AR view to a clip for evaluation; nothing is uploaded.
  const recorder = useArRecording((reason) =>
    Alert.alert(t(reason === 'unsupported' ? 'ar.rec.unsupported' : reason === 'share' ? 'ar.rec.noShare' : 'ar.rec.failed'))
  );
  const recordingNow = recorder.state !== 'idle';
  const products = useTryOnProducts();
  const tryOnProducts = useMemo(() => products.data ?? [], [products.data]);

  // Colour lips: oils / balms live under the 립케어 chip, and lip skincare (essence, serum, mask) is not in the AR lip tab at all.
  const colorProducts = useMemo(
    () => tryOnProducts.filter((p) => p.makeupZone !== 'lip' || (lipCareKind(p) === null && !isLipBaseCare(p))),
    [tryOnProducts]
  );
  const zoneSwatches = useMemo(
    () =>
      colorProducts
        .filter((p) => p.makeupZone === zone)
        .flatMap((p) => p.shades.map((shade) => ({ product: p, shade }))),
    [colorProducts, zone]
  );
  const careSwatches = useMemo(
    () =>
      zone !== 'lip'
        ? []
        : tryOnProducts
            .filter((p) => p.makeupZone === 'lip' && lipCareKind(p) !== null)
            .flatMap((p) => p.shades.map((shade) => ({ product: p, shade }))),
    [tryOnProducts, zone]
  );
  const selectedCare = useMemo(
    () =>
      careSelection
        ? careSwatches.find((i) => i.product.id === careSelection.productId && i.shade.id === careSelection.shadeId) ?? null
        : null,
    [careSwatches, careSelection]
  );
  const selectedTryOn = useMemo(
    () =>
      zoneSwatches.find(
        (item) => selections[zone]?.productId === item.product.id && selections[zone]?.shadeId === item.shade.id
      ),
    [zoneSwatches, selections, zone]
  );
  // 11-17 v7: a metallic eyeshadow (read from its name) is drawn as a metallic glitter and labelled next to its name.
  const shadowMetal =
    zone === 'eyeshadow' && !!selectedTryOn && glitterTraitsOf(selectedTryOn.product.name, selectedTryOn.shade.name).metal;
  const explorationScope = JSON.stringify([routeProductId, routeShadeId, activeLook?.id]);
  const nearby = useNearbyExploration(tryOnProducts, zone, selectedTryOn, textureFilter, explorationScope);
  // Filter chips: only textures / color families present in this zone; families for lips only.
  const textureOptions = useMemo(
    () =>
      zone === 'lip'
        ? LIP_TEXTURE_CHIPS.filter((tx) => zoneSwatches.some(({ product }) => lipTextureChip(product.texture) === tx))
        : TEXTURES.filter((tx) => zoneSwatches.some(({ product }) => product.texture === tx)),
    [zoneSwatches, zone]
  );
  const foundationSwatches = useMemo(() => colorProducts.filter(p => p.makeupZone === 'foundation')
    .flatMap(product => product.shades.map(shade => ({ product, shade }))).filter(usableShadeTone), [colorProducts]);
  // Foundation shades closest to the measured skin color (a color reference only).
  const foundMatches = useMemo(
    () =>
      zone === 'foundation' && skinTone && skinTone.conf >= MIN_TONE_CONF
        ? rankFoundationShades(skinTone, foundationSwatches).slice(0, 3)
        : [],
    [zone, skinTone, foundationSwatches]
  );
  const familyOptions = useMemo(
    () => zone === 'lip' ? COLOR_FAMILIES.filter((fm) => zoneSwatches.some(({ shade }) => colorFamily(shade.hex) === fm)) : [],
    [zoneSwatches, zone]
  );
  const careOpen = zone === 'lip' && careChip !== null;
  const visibleSwatches = useMemo(
    () =>
      careOpen
        ? careSwatches.filter(({ product }) => careChip === 'all' || lipCareKind(product) === careChip)
        : zoneSwatches.filter(
            ({ product, shade }) =>
              (!textureFilter ||
              (zone === 'lip' ? lipTextureChip(product.texture) === textureFilter : product.texture === textureFilter)) &&
              (!familyFilter || colorFamily(shade.hex) === familyFilter)
          ),
    [careOpen, careChip, careSwatches, zoneSwatches, zone, textureFilter, familyFilter]
  );
  const canExplore = !fit && !practice && !fromVideo;
  const direct = mode === 'direct' && canExplore;
  const paletteShown = direct && !sheet && !zoneMenuOpen && !isFullscreenAR;
  const activity = useArHistory({
    active: cameraActive && canExplore, zone, direction: nearby.direction,
    nearby: nearby.active ? nearby.groups[nearby.direction] : null,
    catalog: zoneSwatches, visibleItems: visibleSwatches, paletteShown,
    prepareVoiceRecommendations: mode === 'chat', careOpen,
    scopeKey: explorationScope, filterKey: JSON.stringify([textureFilter, familyFilter]),
  });
  const displayedSwatches = activity.ordered;
  const displayedFamilies = nearby.active ? [] : familyOptions;

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
    }
  }
  if (!isArPaintZone(zone)) setZone('lip');

  // No lip is applied on entry (11-10, user): until a shade is picked the camera shows the user's own lips.

  useFocusEffect(
    useCallback(() => {
      setStatus('loading');
      return () => {
        endFit();
        clearLookMascara();
      };
    }, [endFit, clearLookMascara])
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
  const rendererMounted = !!liveCamera && cameraActive;
  const applyDirect = (product: Product, shade: Shade, fromPalette = false) => {
    applyShade(product, shade);
    if (fromPalette && !careOpen && !nearby.active && nearby.supported && recommendHint === 'new' &&
        ![shade.measureMethod, shade.colorSource].includes('placeholder') && product.texture) setRecommendHint('visible');
    if (!direct || !rendererMounted || status !== 'tracking' || !activity.history || !product.makeupZone) return;
    const state = useMakeupStore.getState();
    const selection = [state.selections[product.makeupZone], state.careSelection]
      .find(s => s?.productId === product.id && s.shadeId === shade.id);
    if (selection) void activity.history.event('try_on', selection, product.makeupZone,
      fromPalette && activity.view?.contains(product.id, shade.id) ? activity.view : undefined).catch(noteArFailure);
  };
  const rendererId = useMemo(() => [arKey, rendererMounted, uuid.v4()].join(':'), [arKey, rendererMounted]);
  const submittedDraft = useRef<string | null>(null);

  // A member who consented at signup only needs the operating system permission.
  const requestedPermission = useRef(false);
  useEffect(() => {
    if (!cameraActive) requestedPermission.current = false;
    if (isWeb || !cameraActive || !cameraChoice.granted || permission?.status !== 'undetermined' || requestedPermission.current) return;
    requestedPermission.current = true;
    void requestPermission().catch(() => {});
  }, [cameraActive, cameraChoice.granted, isWeb, permission?.status, requestPermission]);

  const onAllow = async () => {
    if (cameraChoice.member && !cameraChoice.granted) return router.push('/terms-consent');
    if (!cameraChoice.member) setCameraConsent(true);
    setSwatchOnly(false);
    if (!isWeb && !permission?.granted) await requestPermission();
  };

  const retry = () => {
    setStatus('loading');
    setArKey((k) => k + 1);
  };

  // The WebView's renderer died: restart only the AR page. A second death within a minute stops the automatic restart
  // and shows the swatch fallback with the retry button, so a device that cannot run it does not loop.
  const crashTimes = useRef<number[]>([]);
  const onArCrash = useCallback(() => {
    const now = Date.now();
    crashTimes.current = [...crashTimes.current.filter((at) => now - at < 60_000), now];
    if (crashTimes.current.length >= 2) {
      setStatus('unavailable');
      return;
    }
    setStatus('loading');
    setArKey((k) => k + 1);
  }, []);

  const exitToPrevious = useCallback(() => {
    if (router.canGoBack()) router.back();
    else router.replace('/(tabs)');
  }, [router]);
  const backToProduct = () => exitAr(() => {
    if (router.canGoBack()) router.back();
    else if (routeProductId) router.push(productHref(routeProductId, routeShadeId));
    else exitToPrevious();
  });

  const selectionItems = [...Object.values(selections).filter(Boolean), ...(careSelection ? [careSelection] : [])];
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
  const gaps = useMemo(() => findColorGaps(makeup, wornLines, colorProducts), [makeup, wornLines, colorProducts]);
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
  const showRecs = !nearby.supported && recFor !== null && recFor === recKey;
  const recs = useMemo(() => {
    if (!showRecs || !zoneHex) return [];
    const sel = selections[zone];
    return recommendShades(zoneHex, zone, colorProducts, sel ?? null);
  }, [showRecs, zoneHex, zone, colorProducts, selections]);
  const onAddFit = () => {
    if (!fit) return;
    addToCart({ productId: fit.productId, shadeId: fit.shadeId });
    setAdded(true);
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
  };
  function prepareCartAddition(selection: { productId: string; shadeId: string }, makeupZone?: MakeupZone | null) {
    const event = direct && makeupZone ? activity.history?.cartAdd(selection, makeupZone) : undefined;
    return {
      item: {
        productId: selection.productId,
        shadeId: selection.shadeId,
        addedFromLookId: activeLook?.id,
        ...(event?.source ? { arCartSources: [event.source] } : {}),
      },
      record: event?.record,
    };
  }
  function recordCartIncrease(addition: ReturnType<typeof prepareCartAddition>,
    before: ReturnType<typeof useCartStore.getState>['items']) {
    if (!addition.record) return;
    const { productId, shadeId } = addition.item;
    const quantity = (items: typeof before) => items.find(i =>
      i.productId === productId && i.shadeId === shadeId)?.quantity ?? 0;
    if (quantity(useCartStore.getState().items) > quantity(before)) {
      addition.record();
    }
  }
  const onAddSelection = () => {
    if (added) {
      router.push('/cart');
      return;
    }
    const before = useCartStore.getState().items;
    const additions = selectionItems.flatMap(s => s
      ? [prepareCartAddition(s, tryOnProducts.find(p => p.id === s.productId)?.makeupZone)]
      : []);
    addMany(additions.map(addition => addition.item));
    for (const addition of additions) recordCartIncrease(addition, before);
    setAdded(true);
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
  };

  const wing = makeup.eyeliner?.geometry;
  const practicing = !!practice;
  const zonesOfSteps = useMemo(
    () => practiceZones(makeup, stepOrder).filter((z) => z === null || isArPaintZone(z)),
    [makeup, stepOrder]
  );
  const practiceIndex = practice ? Math.min(practice.index, zonesOfSteps.length - 1) : 0;
  const practiceZone = zonesOfSteps[practiceIndex] ?? null;
  // Video look finish strength (1 = the look's tuned values), kept per look so a new look starts from 1.
  const [lookStrengthPick, setLookStrengthPick] = useState<{ lookId: string | null; value: number }>({ lookId: null, value: LOOK_STRENGTH_DEFAULT });
  const lookStrength = lookStrengthPick.lookId === (activeLook?.id ?? null) ? lookStrengthPick.value : LOOK_STRENGTH_DEFAULT;
  const setLookStrength = (value: number) => setLookStrengthPick({ lookId: activeLook?.id ?? null, value });
  const lookFinishOn = fromVideo && !fit && !routeProductId && !!activeLook && isDemoLook(activeLook.id);
  const onPoseHint = useCallback((hint: PoseHint | null) => {
    if (lookFinishOn || hint === null) setPoseHint(hint);
  }, [lookFinishOn]);
  const lookTitleKey = activeLook ? demoLookTitleKey(activeLook.id) : null;
  const lookDisplayTitle = lookTitleKey ? t(lookTitleKey) : (activeLook?.title ?? '');
  const shownMakeup = useMemo(() => {
    const face = practicing && !peek && practice ? revealedMakeup(makeup, practice.visited) : makeup;
    return videoLookMakeup(arPaintMakeup(face), {
      fromVideo, cameraActive, fittingProduct: !!fit || !!routeProductId,
      lookId: activeLook?.id ?? null, modified, strength: lookStrength,
    });
  }, [practicing, peek, practice, makeup, fromVideo, cameraActive, fit, routeProductId, activeLook?.id, modified, lookStrength]);
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

  useFocusEffect(useCallback(() => {
    const sub = BackHandler.addEventListener('hardwareBackPress', () => {
      if (isFullscreenAR) setMirrorMode(false);
      else if (sheet) setSheet(null);
      else if (zoneMenuOpen) setZoneMenuOpen(false);
      else void exitAr(exitToPrevious);
      return true;
    });
    return () => sub.remove();
  }, [exitAr, exitToPrevious, isFullscreenAR, setMirrorMode, sheet, zoneMenuOpen]));

  useFocusEffect(
    useCallback(() => {
      navigation.setOptions({ tabBarStyle: HIDDEN_TAB_BAR_STYLE });
      return () => {
        setSheet(null);
        setAddedShade(null);
        setIsFullscreenAR(false);
        clearConversation();
        navigation.setOptions({ tabBarStyle: TAB_BAR_STYLE });
      };
    }, [navigation, clearConversation])
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

  const currentSwatch = careOpen ? selectedCare : selectedTryOn;
  const paletteSelection = shadowPointing ? displayedSwatches.find(s => s.shade.hex === makeup.eyeshadow?.hexTo) : currentSwatch;
  const center = Math.max(0, displayedSwatches.findIndex(s => s.product.id === paletteSelection?.product.id && s.shade.id === paletteSelection?.shade.id));
  const displayMode = liveCamera ? 'face' : swatchOnly ? 'swatches_only' : 'unavailable';
  const tracking = rendererMounted && status === 'tracking';
  const catalogReady = !products.isError && !products.isPending;
  const choices = new Map<string, ControlOperation>();
  const { apply, recommend } = makeupControls(choices, { products: tryOnProducts, ready: catalogReady, display: displayedSwatches,
    center, tracking, swatchesOnly: swatchOnly, faceShape, visibleMakeup:shownMakeup,
    faceTemporarilyMissing: rendererMounted && status === 'no-face',
    shadowPointing,
    onShadowPointCleared: () => setShadowPointMode(false),
    onShadeSelected: (selectedZone, care, _item, point) => {
      if (zone !== selectedZone) chooseZone(selectedZone);
      if (care || careOpen) setCareChip(care);
      if (mode === 'chat' && selectedZone === 'eyeshadow') setShadowPointMode(point);
    } });
  const change = (same: boolean, perform: () => void, data: unknown) => {
    if (same) return result('NO_CHANGE', data);
    perform();
    return result('APPLIED', data);
  };
  for (const z of AR_PAINT_ZONES) choices.set('select_zone/' + z, () => change(zone === z, () => chooseZone(z),
    { activeZone: z, count: zone === z ? displayedSwatches.length : colorProducts.filter(p => p.makeupZone === z).reduce((n,p) => n + p.shades.length,0) }));
  const filter = (texture: Texture | null, family: ColorFamily | null, care: typeof careChip, keepNearby = false) => {
    if (!catalogReady) return reject('catalog unavailable');
    const staysNearby = keepNearby && nearby.active;
    const count = staysNearby ? nearby.candidates(nearby.direction, texture).length :
      care ? careSwatches.filter(s => care === 'all' || lipCareKind(s.product) === care).length :
      zoneSwatches.filter(s => (!texture || (zone === 'lip' ? lipTextureChip(s.product.texture) : s.product.texture) === texture) &&
        (!family || colorFamily(s.shade.hex) === family)).length;
    const leavesNearby = nearby.active && !staysNearby;
    return change(!leavesNearby && texture === textureFilter && family === familyFilter && care === careChip, () => {
      if (leavesNearby) {
        activity.returnFromNearby(selectedTryOn);
        nearby.leave();
      }
      setTextureFilter(texture);
      setFamilyFilter(family);
      setCareChip(care);
    }, { texture, family, care, count, nearby: staysNearby,
      ...(staysNearby && { anchor: shadeInfo(nearby.anchor), direction: nearby.direction }) });
  };
  const setTexture = (texture: Texture | null) => filter(texture, familyFilter, null, true);
  choices.set('set_palette_filter/reset', () => filter(null, null, null));
  choices.set('set_palette_filter/texture/reset', () => setTexture(null));
  for (const tx of textureOptions) choices.set('set_palette_filter/' + tx, () => setTexture(tx));
  if (displayedFamilies.length) choices.set('set_palette_filter/family/reset', () => filter(textureFilter, null, null));
  for (const fm of displayedFamilies) {
    choices.set('set_palette_filter/' + fm, () => filter(textureFilter, fm, null));
    for (const tx of textureOptions) choices.set('set_palette_filter/' + fm + '/' + tx, () => filter(tx, fm, null));
  }
  if (zone === 'lip') for (const k of ['all','oil','balm'] as const) choices.set('set_palette_filter/lipCare/' + k, () => filter(null,null,k));
  if (nearby.supported) {
    for (const dir of NEARBY_DIRECTIONS) {
      choices.set('explore_nearby/show/' + dir, () => {
        if (!nearby.active && !nearby.canEnter) return reject('no applied anchor shade');
        const items = nearby.candidates(dir);
        return change(nearby.active && nearby.direction === dir, () => {
          setCareChip(null);
          if (nearby.active) nearby.setDirection(dir);
          else { activity.beginNearby(); nearby.enter(dir); }
        }, { anchor: shadeInfo(nearby.anchor ?? selectedTryOn), direction: dir, count: items.length, shades: items.slice(0,5).map(shadeInfo) });
      });
      if (nearby.active || nearby.canEnter) choices.set('explore_nearby/apply/' + dir, (_,c) => {
        if (!catalogReady) return reject('catalog unavailable');
        const matches = nearby.candidates(dir);
        return recommend(matches[0], c);
      });
    }
    choices.set('explore_nearby/rebase', () => nearby.canRebase ? change(false, nearby.rebase, shadeInfo(selectedTryOn)) : reject('no new anchor'));
    choices.set('explore_nearby/back', () => nearby.canGoBack ? change(false, nearby.back, 'previous anchor') : reject('no previous anchor'));
    choices.set('explore_nearby/exit', () => change(!nearby.active, () => {
      activity.returnFromNearby(selectedTryOn);
      nearby.leave();
    }, { active: false }));
    choices.set('explore_nearby/apply_anchor', (_,c) => apply(nearby.anchor,c));
  }
  const recommendationScope = JSON.stringify([explorationScope, zone, textureFilter, familyFilter, careChip,
    shadeInfo(nearby.anchor), nearby.direction, shadowPointing, practicing, fit]);
  const recentRecommendations = recommendationList && voiceActive && catalogReady &&
    recommendationList.catalog === tryOnProducts && recommendationList.scope === recommendationScope &&
    (recommendationList.kind !== 'personalized' || activity.canRecommend) ? recommendationList : null;
  if (recommendationList && !recentRecommendations) setRecommendationList(null);
  const showRecommendations = (kind: RecommendationKind, items: readonly ColorSwatch[]) => {
    setRecommendationList({ kind, items, scope: recommendationScope, catalog: tryOnProducts });
    return result('OK', items.map(shadeInfo));
  };
  if (recentRecommendations) {
    recentRecommendations.items.forEach((item, index) => {
      const target = recentRecommendations.kind + '/' + (index + 1);
      choices.set('apply_recommendation/' + target, (_, confirm) => recommend(item, confirm));
      choices.set('navigate/recommendation/' + target, () => {
        router.push(productHref(item.product.id, item.shade.id));
        return result('APPLIED', { destination: 'product', ...shadeInfo(item) });
      });
    });
  }
  const foundationMatches = () => zone === 'foundation' ? foundMatches : skinTone && skinTone.conf >= MIN_TONE_CONF
    ? rankFoundationShades(skinTone, foundationSwatches).slice(0, 3) : [];
  choices.set('apply_shade/foundation/skin_match', (_, confirm) => {
    if (!skinTone || skinTone.conf < MIN_TONE_CONF) return reject('skin tone measurement required');
    return recommend(foundationMatches()[0], confirm);
  });
  choices.set('get_recommendations/foundation_match', () => {
    if (!catalogReady || !skinTone || skinTone.conf < MIN_TONE_CONF) return reject('catalog or skin tone measurement required');
    return showRecommendations('foundation_match', foundationMatches());
  });
  choices.set('get_recommendations/look_gap', () => !catalogReady ? reject('catalog unavailable') :
    showRecommendations('look_gap', zoneGap?.kind === 'nearest' && !selectedLine ? [zoneGap.nearest] : []));
  choices.set('get_recommendations/similar_shades', () => {
    if (!catalogReady) return reject('catalog unavailable');
    if (nearby.supported) {
      if (!nearby.active && !nearby.canEnter) return reject('no applied anchor shade');
      return showRecommendations('similar_shades', nearby.candidates('similar').slice(0, 5));
    }
    if (!zoneHex) return reject('no current shade');
    return showRecommendations('similar_shades', recommendShades(zoneHex, zone, colorProducts, selections[zone] ?? null));
  });
  if (canExplore && (zone === 'lip' || zone === 'blush') && !nearby.active && !careOpen) {
    const unavailable = () => reject(!activity.canRecommend ? 'personalized recommendations unavailable' : 'personalized recommendations loading');
    choices.set('get_recommendations/personalized', () => !catalogReady ? reject('catalog unavailable') :
      activity.recommendationsReady ? showRecommendations('personalized', activity.recommendations ?? []) : unavailable());
    choices.set('apply_shade/' + zone + '/personalized', (_, confirm) => !catalogReady ? reject('catalog unavailable') :
      activity.recommendationsReady ? recommend(activity.recommendations?.[0], confirm) : unavailable());
  }
  choices.set('set_shadow_point/show', () => {
    if (!makeup.eyeshadow || practicing) return reject('no eyeshadow palette available');
    return change(!!shadowPointing && !sheet && !isFullscreenAR, () => {
      if (zone !== 'eyeshadow') chooseZone('eyeshadow');
      setShadowPointMode(true);
      setSheet(null);
      if (isFullscreenAR) setMirrorMode(false);
    }, { shadowPointing: true });
  });
  choices.set('set_shadow_point/hide', () => change(!shadowPointMode && !shadowPointing, () => {
    setShadowPointMode(false);
  }, { shadowPointing: false }));
  for (const on of [true,false]) {
    const key = on ? 'on' : 'off';
    choices.set('set_view/compare/' + key, () => liveCamera ? change(compare === on, () => setCompare(on), {compare:on}) : reject('camera required'));
    choices.set('set_view/mirror/' + key, () => liveCamera ? change(isFullscreenAR === on, () => {
      if (on) setSheet(null);
      setMirrorMode(on);
    }, { mirror: on }) : reject('camera required'));
  }
  for (const panel of ['tools','product','info',null] as const) choices.set('set_view/panel/' + (panel ?? 'closed'), () =>
    panel === 'product' && !currentSwatch ? reject('no selected product') : change(sheet === panel, () => {
      if (panel && isFullscreenAR) setMirrorMode(false);
      setSheet(panel);
    }, { panel }));
  for (const m of ['direct','chat'] as const) choices.set('set_view/mode/' + m, () => change(mode === m, () => switchMode(m), {mode:m}));
  for (const target of ['current_product','fit_product','all_selected'] as const) choices.set('add_to_cart/' + target, () => {
    const currentSelection = careOpen ? careSelection : selections[zone];
    const selected = target === 'fit_product' ? (fit ? [fit] : []) : target === 'all_selected' ? selectionItems :
      currentSwatch && currentSelection ? [currentSelection] : [];
    if (!catalogReady) return reject('catalog unavailable');
    const additions = selected.flatMap(s => {
      if (!s) return [];
      const product = tryOnProducts.find(p => p.id === s.productId && p.shades.some(sh => sh.id === s.shadeId));
      return product ? [prepareCartAddition(s, product.makeupZone)] : [];
    });
    if (!additions.length) return reject('no selected product');
    const before = useCartStore.getState().items;
    const lines = additions.map(addition => addition.item);
    addMany(lines);
    for (const addition of additions) recordCartIncrease(addition, before);
    const items = useCartStore.getState().items;
    return result(JSON.stringify(before) === JSON.stringify(items) ? 'NO_CHANGE' : 'APPLIED',
      items.filter(i => lines.some(l => i.productId === l.productId && i.shadeId === l.shadeId)).map(i => {
        const product = tryOnProducts.find(p => p.id === i.productId);
        const shade = product?.shades.find(s => s.id === i.shadeId);
        return {...i, ...shadeInfo(product && shade ? {product,shade} : undefined),
          beforeQuantity:before.find(l => l.productId === i.productId && l.shadeId === i.shadeId)?.quantity ?? 0};
      }));
  });
  choices.set('navigate/product', () => {
    const target = fit ?? (careOpen ? careSelection : selections[zone]);
    if (!target || !catalogReady || !tryOnProducts.some(p => p.id === target.productId && p.shades.some(s => s.id === target.shadeId)))
      return reject('no available selected product');
    router.push(productHref(target.productId,target.shadeId)); return result('APPLIED', {destination:'product',...target});
  });
  choices.set('navigate/store', async () => {
    const url = currentSwatch?.product.sourceUrl;
    if (!isSafeExternalUrl(url)) return reject('no merchant link');
    await WebBrowser.openBrowserAsync(url!); return result('APPLIED', shadeInfo(currentSwatch));
  });
  choices.set('navigate/cart', () => change(false, () => router.push('/cart'), 'cart'));
  choices.set('navigate/back', () => router.canGoBack() ? change(false, router.back, 'back') : reject('no previous screen'));
  choices.set('navigate/similar_products', () => zoneSelection && !nearby.supported ?
    change(false, openRecommendations, zoneSelection) : reject('no current selection or unavailable'));
  choices.set('control_practice/start', () => change(practicing, () => {
    setSheet(null);
    if (isFullscreenAR) setMirrorMode(false);
    startPractice();
  }, practiceSteps[0]));
  if (practicing) {
    choices.set('control_practice/exit', () => change(false, exitPractice, {active:false}));
    for (const on of [true,false]) choices.set('control_practice/peek_' + (on?'on':'off'), () => change(peek===on, () => setPeek(on), {peek:on}));
    const stepTo = (i:number) => i >= practiceSteps.length ? change(false, exitPractice, {active:false}) :
      change(practiceIndex === Math.max(0,i), () => goToStep(i), practiceSteps[Math.max(0,i)]);
    choices.set('control_practice/next', () => stepTo(practiceIndex+1));
    choices.set('control_practice/previous', () => stepTo(practiceIndex-1));
    practiceSteps.forEach((s,i) => choices.set('control_practice/go_to/' + (i+1) + '/' + s.key, () => stepTo(i)));
  }
  for (const dir of ['up','down','absolute']) choices.set('set_look_strength/' + dir, async ({value}, confirm) => {
    if (!lookFinishOn) return reject('no adjustable video look');
    const next = dir === 'absolute' ? value : Math.max(LOOK_STRENGTH_MIN,Math.min(LOOK_STRENGTH_MAX,
      Math.round((lookStrength + (dir==='up'?0.1:-0.1))*100)/100));
    if (next == null || next < LOOK_STRENGTH_MIN || next > LOOK_STRENGTH_MAX) return reject('outside look strength range');
    const data = {before:lookStrength,after:next,look:activeLook?.id};
    if (next === lookStrength) return result('NO_CHANGE', data);
    if (!tracking) return reject('face tracking required');
    const frame = await confirm(makeup, next);
    if (frame === 'stale') return reject('state changed');
    if (frame !== 'rendered') return result(frame === 'failed' ? 'FAILED' : 'UNKNOWN');
    setLookStrength(next);
    return result('APPLIED', data);
  });
  choices.set('retry_catalog', async () => {
    if (!products.isError) return result('NO_CHANGE','catalog not in error');
    const refreshed = await products.refetch();
    return refreshed.isError ? result('FAILED','catalog load failed') : result('APPLIED', {count:refreshed.data?.filter(p=>p.makeupZone===zone).reduce((n,p)=>n+p.shades.length,0)});
  });
  choices.set('control_camera/swatches_only', () => change(swatchOnly, () => setSwatchOnly(true), {displayMode:'swatches_only'}));
  choices.set('control_camera/open_settings', async () => { await Linking.openSettings(); return result('APPLIED','system settings opened'); });
  choices.set('control_camera/request_access', async () => {
    if (cameraChoice.loading || (cameraChoice.member && !cameraChoice.granted)) return reject('camera consent required');
    if (permissionBlocked) return reject('camera permission blocked');
    if (liveCamera) return result('NO_CHANGE','camera already enabled');
    if (!permissionGranted && !(await requestPermission()).granted) return reject('camera permission denied');
    if (!cameraChoice.member) setCameraConsent(true);
    setSwatchOnly(false);
    if (status === 'denied' || status === 'unavailable') retry();
    return result('APPLIED',{permission:'granted',trackingConfirmed:false});
  });
  choices.set('control_camera/retry', () => {
    if (swatchOnly || !cameraConsent || !permissionGranted) return reject('camera access required');
    if (tracking) return result('NO_CHANGE','already tracking');
    retry();
    return result('APPLIED',{cameraStatus:'loading',trackingConfirmed:false});
  });
  const tryOnCounts = useMemo(() => (tryOnHistory ?? []).reduce<Record<string, number>>((counts, entry) => {
    counts.all++;
    counts[entry.zone] = (counts[entry.zone] ?? 0) + 1;
    return counts;
  }, { all: 0 }), [tryOnHistory]);
  const screenState = { zone, displayMode, tracking, mode, sheet, compare, mirror:isFullscreenAR, fit:fit?.productId,
    tryOnCounts,
    look:activeLook?.id, lookStrength, practice:practicing ? practiceIndex : null, peek,
    catalogReady, catalogError:products.isError, cameraStatus:status, permission:permission?.status,
    foundationMeasured:!!skinTone && skinTone.conf >= MIN_TONE_CONF, lookStrengthAvailable:lookFinishOn,
    current:shadeInfo(selectedTryOn), care:shadeInfo(selectedCare), center:shadeInfo(displayedSwatches[center]),
    anchor:shadeInfo(nearby.anchor), direction:nearby.direction, textureFilter, familyFilter, careChip,
    shadowPointing,
    recommendations:recentRecommendations && {kind:recentRecommendations.kind, items:recentRecommendations.items.map(shadeInfo)},
    lipTypes:['lipstick','tint','gloss'],
    count:displayedSwatches.length, worn:AR_PAINT_ZONES.map(z=>worn(useMakeupStore.getState(),z,tryOnProducts,shownMakeup)) };
  choices.set('get_state/' + zone, () => result('OK', { ...worn(useMakeupStore.getState(),zone,tryOnProducts),
    center:screenState.center, anchor:screenState.anchor, activeZone:zone }));
  const summary = JSON.stringify(screenState);
  choices.set('get_state/current_screen', () => result('OK', screenState));
  choices.set('get_state/palette_center', () => result('OK', {center:screenState.center, worn:screenState.current}));
  choices.set('get_state/exploration_anchor', () => result('OK', {anchor:screenState.anchor, direction:nearby.direction}));
  if (fit || practicing) {
    for (const choice of choices.keys()) {
      const common = DETAIL_CONTROL_CHOICES.has(choice) || choice.startsWith('get_state/') || choice.startsWith('control_camera/');
      const specific = fit ? choice === 'add_to_cart/fit_product' || choice === 'navigate/product' :
        choice.startsWith('control_practice/') || (lookFinishOn && choice.startsWith('set_look_strength/'));
      if (!common && !specific) choices.delete(choice);
    }
  }
  // A catalog pick can start while the catalog or face tracker is warming up.
  // Keep it bound to the user's view and filters, independently of readiness notifications.
  const catalogApplyKey = JSON.stringify([zone, mode, displayMode, sheet, compare, isFullscreenAR,
    fit?.productId, activeLook?.id, lookStrength, practicing, practiceIndex, peek, textureFilter,
    familyFilter, careChip, shadowPointing, screenState.anchor, nearby.direction]);
  const control: ControlScreen = {summary, choices, displayMode, contextKey:summary, catalogApplyKey,
    matchCatalog: message => catalogMatches(tryOnProducts, message) };
  const arCommand = useArCommand({active:cameraActive, enabled:tracking, locale:language, rendererId, activeZone:zone, control,
     visibleZones: practicing && !peek && practice ? practice.visited : null,
     fallbackText:r => {
       const label = r.featuredShade ? [
         r.featuredShade.family && t(`ar.family.${r.featuredShade.family}`), r.featuredShade.brand,
         language === 'ko' && r.featuredShade.productKo || r.featuredShade.product, r.featuredShade.shade,
       ].filter(Boolean).join(' · ') : '';
       if (r.renderPending) return t('ar.control.selectionPending', { shade: label });
       return label || t(r.status === 'OK' ? 'ar.control.checked' : r.status === 'APPLIED' ? 'ar.control.changed' :
         r.status === 'NO_CHANGE' ? 'ar.control.unchanged' : AR_COMMAND_STATUS[r.status.toLowerCase() as keyof typeof AR_COMMAND_STATUS]);
     },
    preview:(face,strength=lookStrength,edited=modified)=>videoLookMakeup(arPaintMakeup(practicing && !peek && practice ? revealedMakeup(face,practice.visited) : face),
      {fromVideo,cameraActive,fittingProduct:!!fit || !!routeProductId,lookId:activeLook?.id ?? null,modified:edited,strength})});
  const commandBusy = arCommand.state==='interpreting' || arCommand.state==='proposed' ||
    arCommand.state==='applying' || arCommand.restoreState==='pending';
  async function submitRequest(text: string, signal?: AbortSignal, onPainted?: () => void) {
    if (!cameraActive || !text || commandBusy || submittedDraft.current) return;
    submittedDraft.current = text;
    setChatRequest(text);
    setSendingChat(true);
    try { return await arCommand.send(text, signal, undefined, onPainted); }
    finally { submittedDraft.current = null; setSendingChat(false); }
  }
  const voiceEnabled = voiceActive && mode === 'chat' && !isFullscreenAR && !sheet;
  const useIntegratedVoice = !!integratedVoiceModel && language === 'ko';
  const recordedVoice = useArVoice(voiceEnabled && !useIntegratedVoice, submitRequest, () => {
    const recommendationPalette = recentRecommendations?.items;
    return arVoiceKeywords(tryOnProducts, recommendationPalette ?? displayedSwatches, recommendationPalette ? 0 : center,
      [zoneSelection, careSelection, ...Object.values(selections)]);
  });
  const integratedVoice = useArVoiceSession(voiceEnabled && useIntegratedVoice && recordedVoice.available, control, arCommand.send);
  const voice = useIntegratedVoice ? { ...recordedVoice, ...integratedVoice } : recordedVoice;
  const keyboardVisible = __DEV__ && (testKeyboard || !voice.available);
  const inConversation = voice.phase !== 'idle';
  const canSendCommand = cameraActive && !!draft.trim() && !commandBusy && !sendingChat && !inConversation;
  const sendCommand = () => {
    if (!canSendCommand || submittedDraft.current) return;
    const speak = voice.beginReply();
    void submitRequest(draft.trim()).then(speak);
    setDraft('');
  };
  let stage: ReactNode;
  if (cameraChoice.loading) {
    stage = <ActivityIndicator color={theme.colors.rose} />;
  } else if (swatchOnly) {
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
        {!cameraChoice.member && (['ar.consentPoint1', 'ar.consentPoint2', 'ar.consentPoint3'] as const).map((key) => (
          <View key={key} style={styles.point}>
            <Ionicons name="shield-checkmark-outline" size={18} color={theme.colors.success} />
            <Text style={styles.pointText}>{t(key)}</Text>
          </View>
        ))}
        <Button label={t(cameraChoice.member && !cameraChoice.granted ? 'consent.review' : 'ar.allowCamera')} icon="camera-outline" onPress={onAllow} style={styles.consentBtn} />
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
          renderCommand={arCommand.renderCommand}
          onRenderResult={arCommand.onRenderResult}
          compare={compare}
          guide={guide}
          fillPreview
          onStatus={(next) => { setStatus(next); if (next !== 'tracking') setPoseHint(null); }}
          onEnv={setArEnv}
          onPoseHint={onPoseHint}
          poseEnabled={lookFinishOn}
          onSkinTone={setSkinTone}
          onFaceFit={onFaceFit}
          onFaceFitStatus={onFaceFitStatus}
          onCrash={onArCrash}
          recording={recorder.wanted}
          onRecorder={recorder.handleMessage}
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
        {status === 'no-face' && !lookFinishOn ? (
          <View style={styles.noFace}>
            <Text style={styles.hintText}>{t('ar.env.noFace')}</Text>
            <View style={styles.noFaceActions}>
              <Pressable onPress={retry} accessibilityRole="button" style={styles.pillBtn}>
                <Text style={styles.pillBtnText}>{t('common.retry')}</Text>
              </Pressable>
              <Pressable onPress={() => setSwatchOnly(true)} accessibilityRole="button" style={styles.pillBtn}>
                <Text style={styles.pillBtnText}>{t('ar.viewSwatches')}</Text>
              </Pressable>
            </View>
          </View>
        ) : status === 'tracking' && !lookFinishOn && envMessage && envMessage !== 'noFace' ? (
          // Look-finish mode shows light/pose/no-face coaching under the slim strength card so the card does not cover it.
          <View style={styles.hintPill} pointerEvents="none">
            <Text style={styles.hintText}>{t(ENV_MESSAGE_KEY[envMessage])}</Text>
          </View>
        ) : null}
        {recordingNow ? (
          // The "not recorded" badge would be false now, so it gives way to this one.
          <View style={[styles.liveBadge, isFullscreenAR && { top: Math.max(12, insets.top + 8) }]} pointerEvents="none">
            <View style={[styles.liveDot, styles.recDot]} />
            <Text style={styles.liveText}>
              {recorder.state === 'saving'
                ? t('ar.rec.saving')
                : `${t('ar.rec.on')} · ${Math.floor(recorder.seconds / 60)}:${String(recorder.seconds % 60).padStart(2, '0')}`}
            </Text>
          </View>
        ) : null}
        {recorder.available && recordingNow ? (
          <Pressable
            onPress={recorder.toggle}
            disabled={recorder.state === 'saving'}
            accessibilityRole="button"
            accessibilityLabel={t(recorder.wanted ? 'ar.rec.stop' : 'ar.rec.start')}
            hitSlop={8}
            style={[styles.recordBtn, { bottom: isFullscreenAR ? Math.max(16, insets.bottom + 12) : 420 }]}>
            {recorder.state === 'saving' ? (
              <ActivityIndicator color={theme.colors.white} size="small" />
            ) : (
              <View style={recorder.wanted ? styles.recordStop : styles.recordDot} />
            )}
          </Pressable>
        ) : null}

      </View>
    );
  } else {
    stage = <View style={styles.camera} />;
  }

  const chooseZone = (next: MakeupZone) => {
    setZone(next);
    if (recommendHint === 'visible') setRecommendHint('done');
    setTextureFilter(null);
    setFamilyFilter(null);
    setCareChip(null);
  };
  const onAddCurrent = () => {
    if (!currentSwatch) return;
    const before = useCartStore.getState().items;
    const selection = careOpen ? careSelection : selections[zone];
    if (selection) {
      const addition = prepareCartAddition(selection, zone);
      addToCart(addition.item);
      recordCartIncrease(addition, before);
    }
    setAddedShade(`${currentSwatch.product.id}:${currentSwatch.shade.id}`);
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
  };
  const currentAdded = !!currentSwatch && addedShade === `${currentSwatch.product.id}:${currentSwatch.shade.id}`;
  const explorationControls = nearby.supported ? (
    <NearbyExplorer
      showHint={recommendHint === 'visible'}
      active={nearby.active}
      canEnter={nearby.canEnter}
      anchor={nearby.anchor}
      canGoBack={nearby.canGoBack}
      onEnter={() => { setRecommendHint('done'); activity.beginNearby(); setCareChip(null); nearby.enter(); }}
      onLeave={() => { activity.returnFromNearby(selectedTryOn); nearby.leave(); }}
      onBack={nearby.back}
      onApplyAnchor={() => {
        if (nearby.anchor) applyDirect(nearby.anchor.product, nearby.anchor.shade);
      }}
    />
  ) : null;
  // The page no longer posts a separate light hint (11-19 env state); look-finish coaching keeps its two light cases.
  const lightHint = envMessage === 'blown' ? 'blown' : envMessage === 'dark' ? 'low' : null;
  const coachHint = lookFinishOn && status === 'tracking'
    ? (lightHint
      ? t(lightHint === 'blown' ? 'ar.lightHint.blown' : 'ar.lightHint.low')
      : poseHint
        ? t(`ar.poseHint.${poseHint}`)
        : null)
    : null;
  const notices = (
    <View style={styles.notices} pointerEvents="box-none">
        {showsDemo ? <Text style={styles.sampleNotice}>{t('ar.demoColors')}</Text> : null}
        {lookFinishOn ? (
          <View style={styles.lookFinishCard}>
            <View style={styles.lookFinishHead}>
              <Text style={styles.lookFinishTitle} numberOfLines={1}>
                {modified.length > 0
                  ? t('ar.lookModified', { title: lookDisplayTitle })
                  : lookDisplayTitle}
              </Text>
              <Text style={styles.lookFinishPct}>{Math.round(lookStrength * 100)}%</Text>
            </View>
            <CoverageBar
              inset
              compact
              value={(lookStrength - LOOK_STRENGTH_MIN) / (LOOK_STRENGTH_MAX - LOOK_STRENGTH_MIN)}
              labels={{ title: t('videoAr.lookStrength'), low: t('videoAr.lookStrengthLow'), high: t('videoAr.lookStrengthHigh') }}
              onChange={(value) => setLookStrength(LOOK_STRENGTH_MIN + value * (LOOK_STRENGTH_MAX - LOOK_STRENGTH_MIN))}
            />
          </View>
        ) : activeLook && !fit ? (
          <Text style={styles.lookBanner} numberOfLines={1}>
            {t(modified.length > 0 ? 'ar.lookModified' : 'ar.lookApplied', { title: lookDisplayTitle || activeLook.title })}
          </Text>
        ) : null}
        {lookFinishOn && status === 'no-face' ? (
          <View style={styles.coachPanel}>
            <Text style={styles.coachText}>{t('ar.noFace')}</Text>
            <View style={styles.noFaceActions}>
              <Pressable onPress={retry} accessibilityRole="button" style={styles.pillBtn}>
                <Text style={styles.pillBtnText}>{t('common.retry')}</Text>
              </Pressable>
              <Pressable onPress={() => setSwatchOnly(true)} accessibilityRole="button" style={styles.pillBtn}>
                <Text style={styles.pillBtnText}>{t('ar.viewSwatches')}</Text>
              </Pressable>
            </View>
          </View>
        ) : coachHint ? (
          <View style={styles.coachPill} pointerEvents="none">
            <Text style={styles.coachText}>{coachHint}</Text>
          </View>
        ) : null}
        {routeSelection.shadeMissing ? (
          <Text style={styles.warnBanner} accessibilityRole="alert">
            {t('chat.selectShade')}
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
    </View>
  );
  const productDetails = currentSwatch ? (
    <View style={styles.productCard}>
      <ProductImage
        uri={currentSwatch.product.imageUrl}
        category={currentSwatch.product.category}
        style={styles.productImage}
        recyclingKey={currentSwatch.product.id}
        compact
      />
      <View style={styles.productCopy}>
        {nearby.active ? <Text style={styles.matchTitle}>{t('ar.explore.preview')}</Text> : null}
        <Text style={styles.matchName} numberOfLines={2}>
          {currentSwatch.product.brand} {currentSwatch.product.name}
          {shadowMetal ? ` · ${t('ar.shadow.metalTag')}` : ''}
        </Text>
        <Text style={styles.matchNote} numberOfLines={1}>
          {currentSwatch.shade.name}
          {currentSwatch.product.priceKRW > 0 ? ` · ${formatKRW(currentSwatch.product.priceKRW)}` : ''}
        </Text>
        {nearby.active && nearby.canRebase ? (
          <Button label={t('ar.explore.rebase')} icon="search-outline" compact variant="secondary" onPress={() => { nearby.rebase(); setSheet(null); }} />
        ) : null}
        {currentSwatch.shade.measureMethod === 'estimated' ? (
          <Text style={styles.foundNote}>{t('ar.shadeEstimated')}</Text>
        ) : null}
        <View style={styles.productLinks}>
          <Chip
            label={t('ar.openProduct')}
            onPress={() =>
              router.push({
                pathname: '/product/[id]',
                params: { id: currentSwatch.product.id, shade: currentSwatch.shade.id },
              })
            }
          />
          {isSafeExternalUrl(currentSwatch.product.sourceUrl) ? (
            <Chip
              label={t('ar.openStore')}
              onPress={() => WebBrowser.openBrowserAsync(currentSwatch.product.sourceUrl!)}
            />
          ) : null}
        </View>
      </View>
    </View>
  ) : null;
  const detailPanel = (
      <View style={styles.panel}>
        {(fit || practicing) && liveCamera ? <Pressable accessibilityRole="button" accessibilityLabel={t('ar.mirror.enter')} onPress={() => setMirrorMode(true)} style={styles.panelFold}>
          <Ionicons name="chevron-down" size={20} color={theme.colors.ink} />
        </Pressable> : null}
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
                onPress={() => { void exitAr(() => router.push({ pathname: '/product/[id]', params: { id: fit.productId, shade: fit.shadeId } })); }}
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
        ) : null}
        <Text style={styles.disclaimer}>{t('ar.disclaimer')}</Text>
      </View>
  );

  return (
    <View style={styles.screen}>
      <View style={StyleSheet.absoluteFill}>{stage}</View>
      <LinearGradient pointerEvents="none" colors={['transparent', 'rgba(25,15,21,0.84)']} style={styles.bottomShade} />
      <SafeAreaView pointerEvents="box-none" style={styles.overlayScreen} edges={['top', 'left', 'right']}>
        <View pointerEvents="box-none" style={styles.topbar}>
          <Pressable accessibilityRole="button" accessibilityLabel={t('common.back')} style={styles.topIcon}
            onPress={() => { if (isFullscreenAR) setMirrorMode(false); else void exitAr(exitToPrevious); }}>
            <View style={styles.topIconVisual}><Ionicons name="chevron-back" size={20} color="#FFFFFF" /></View>
          </Pressable>
          {!isFullscreenAR && !practicing && !fit ? (
            <View style={styles.modeRow}>
              <View pointerEvents="none" style={styles.modeBackground} />
              {(['direct', 'chat'] as const).map((m) => (
                <Pressable key={m} accessibilityRole="tab" accessibilityState={{ selected: mode === m }}
                  onFocus={() => setFocusedMode(m)} onBlur={() => setFocusedMode(null)}
                  onPress={() => { setSheet(null); switchMode(m); }} style={styles.modeHit}>
                  <View style={[styles.modeTab, mode === m && styles.modeTabActive, Platform.OS === 'web' && focusedMode === m && styles.modeTabFocused]}>
                    <Text style={[styles.modeText, mode === m && styles.modeTextActive]}>{t(m === 'chat' ? 'ar.mode.chat' : 'ar.mode.direct')}</Text>
                  </View>
                </Pressable>
              ))}
            </View>
          ) : null}
          {!isFullscreenAR ? <Pressable accessibilityRole="button" accessibilityLabel={t('cart.title')} style={styles.topIcon} onPress={() => router.push('/cart')}>
            <View style={styles.topIconVisual}><Ionicons name="bag-outline" size={20} color="#FFFFFF" /></View>
            {cartCount > 0 ? <Text style={styles.cartBadge}>{cartCount > 99 ? '99+' : cartCount}</Text> : null}
          </Pressable> : null}
        </View>
        {!isFullscreenAR ? notices : null}
        {!isFullscreenAR && !fit && !practicing && mode === 'direct' ? (
          <View pointerEvents="box-none" style={[styles.railArea, {
            top: insets.top + 64, bottom: dockBottom + AR_DOCK_BODY_HEIGHT + AR_PRODUCT_ROW_HEIGHT + 8,
          }]}>
            <IntensityRail value={currentIntensity} minimum={zone === 'blush' ? BLUSH_INTENSITY_MIN : 0}
              onChange={level => setIntensity(zone, level)} />
          </View>
        ) : null}
        {!isFullscreenAR && !fit && !practicing ? (
          <View testID="ar-side-controls" pointerEvents="box-none" style={[styles.sideControls, { bottom: dockBottom + AR_DOCK_BODY_HEIGHT + AR_PRODUCT_ROW_HEIGHT }]}>
            {mode === 'direct' ? explorationControls : (
              <Pressable accessibilityRole="button" accessibilityLabel={t('ar.mirror.enter')} disabled={!liveCamera}
                accessibilityState={{ disabled: !liveCamera }} onPress={() => setMirrorMode(true)} style={[styles.chatMirror, !liveCamera && { opacity: 0.45 }]}>
                <View style={styles.sideIcon}><Ionicons name="expand-outline" size={19} color="#FFFFFF" /></View>
                <Text style={styles.sideLabel}>{t('ar.arc.mirrorShort')}</Text>
              </Pressable>
            )}
            <View style={styles.leftTools}>
              <Pressable accessibilityRole="button" accessibilityLabel={t('ar.arc.compare')} accessibilityState={{ selected: compare }} onPress={() => setCompare((value) => !value)} style={styles.sideControl}>
                <View style={[styles.sideIcon, compare && styles.selectedTool]}><Ionicons name="contrast-outline" size={19} color="#FFFFFF" /></View>
                <Text style={styles.sideLabel}>{t('ar.arc.compareShort')}</Text>
              </Pressable>
              <Pressable accessibilityRole="button" accessibilityLabel={t(mode === 'direct' ? 'ar.arc.tools' : 'ar.arc.info')} onPress={() => setSheet(mode === 'direct' ? 'tools' : 'info')} style={styles.sideControl}>
                <View style={styles.sideIcon}><Ionicons name={mode === 'direct' ? 'ellipsis-horizontal' : 'information-outline'} size={21} color="#FFFFFF" /></View>
                <Text style={styles.sideLabel}>{t(mode === 'direct' ? 'ar.arc.tools' : 'ar.arc.infoShort')}</Text>
              </Pressable>
            </View>
          </View>
        ) : null}
        {isFullscreenAR ? (
          <Pressable accessibilityRole="button" accessibilityLabel={t('ar.mirror.exit')} onPress={() => setMirrorMode(false)} style={[styles.mirrorExpandBtn, { bottom: Math.max(16, insets.bottom + 12) }]}>
            <Ionicons name="chevron-up" size={22} color="#FFFFFF" />
          </Pressable>
        ) : (fit || practicing) && mode !== 'chat' ? (
          <KeyboardAvoidingView pointerEvents="box-none" style={styles.chatDock} behavior={Platform.OS === 'ios' ? 'padding' : 'height'}>
            <View style={{ flex: 1 }} pointerEvents="none" />
            <ScrollView keyboardShouldPersistTaps="handled" style={{ maxHeight: windowHeight * 0.55, flexGrow: 0 }} contentContainerStyle={{ paddingBottom: Math.max(12, insets.bottom) }}>
              {detailPanel}
            </ScrollView>
          </KeyboardAvoidingView>
        ) : mode === 'chat' ? (
          <KeyboardAvoidingView pointerEvents="box-none" style={styles.chatDock} behavior={Platform.OS === 'ios' ? 'padding' : 'height'}>
            <View style={[styles.chat, { height: AR_PRODUCT_ROW_HEIGHT + AR_DOCK_BODY_HEIGHT + dockBottom, paddingBottom: dockBottom }]}>
              <View testID="ar-current-product" style={styles.currentRow}>
                 <Pressable disabled={!currentSwatch} accessibilityRole="button" accessibilityLabel={t('ar.openProduct')} onPress={() => setSheet('product')} style={styles.currentProduct}>
                   <Text numberOfLines={1} style={styles.currentName}>{currentSwatch ? `${t(`ar.zone.${zone}` as TranslationKey)} · ${currentSwatch.shade.name}` : t('ar.chatFirstProduct')}</Text>
                  <Ionicons name="chevron-forward" size={16} color="#FFFFFF" />
                </Pressable>
                 <Pressable disabled={!currentSwatch} accessibilityRole="button" accessibilityLabel={t('ar.addThisProduct')} onPress={onAddCurrent} style={styles.addCurrent}>
                  <Ionicons name={currentAdded ? 'checkmark' : 'bag-add-outline'} size={23} color="#FFFFFF" />
                </Pressable>
              </View>
              <ScrollView style={styles.chatHistory} contentContainerStyle={styles.chatHistoryContent} keyboardShouldPersistTaps="handled" showsVerticalScrollIndicator={false}>
                {currentAdded ? <Text style={styles.addedNote} accessibilityLiveRegion="polite">{t('ar.addedSelection')}</Text> : null}
                {chatRequest ? (
                  <View style={styles.chatMessages}>
                    <View style={styles.chatUserBubble}><Text style={styles.chatMessageText}>{chatRequest}</Text></View>
                    {arCommand.state !== 'idle' ? (
                      <View style={styles.chatReplyRow}>
                        <Ionicons name="chatbubble-ellipses" size={24} color="#F0DCE3" />
                        <View style={styles.chatReplyBubble}>
                          <Text style={styles.chatMessageText} accessibilityLiveRegion="polite">
                            {arCommand.message || t(AR_COMMAND_STATUS[arCommand.state])}
                          </Text>
                        </View>
                      </View>
                    ) : null}
                  </View>
                ) : keyboardVisible ? (
                  <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.chatSuggestions} contentContainerStyle={styles.chatExamples} keyboardShouldPersistTaps="handled">
                    {CHAT_EXAMPLES.map(({ label, request }) => (
                      <Pressable key={request} accessibilityRole="button" accessibilityLabel={t(request)} onPress={() => setDraft(t(request))} style={styles.chatSuggestion}>
                        <Text style={styles.chatSuggestionText}>{t(label)}</Text>
                      </Pressable>
                    ))}
                  </ScrollView>
                ) : null}
                {arCommand.controlResult && ['APPLIED','NO_CHANGE'].includes(arCommand.controlResult.status) &&
                  /^(select_zone|set_palette_filter|explore_nearby\/show)\//.test(arCommand.controlChoice) ? (
                     displayedSwatches.length ? <OpenArcPalette items={displayedSwatches} selected={currentSwatch ?? undefined}
                       label={t('ar.arc.palette')} hint={t('ar.arc.swipe')} onSelect={({product,shade}) => applyDirect(product,shade)} /> :
                      <Text style={styles.arcEmpty}>{t(nearby.active ? 'ar.explore.empty' : zoneSwatches.length ? 'ar.filter.empty' : 'ar.noProducts')}</Text>
                  ) : null}
                {arCommand.restoreState !== 'idle' || arCommand.ackPending ? <View style={styles.chatStatus}>
                  {arCommand.restoreState !== 'idle' ? <Text style={styles.chatNotice} accessibilityLiveRegion="polite">{t(AR_RESTORE_STATUS[arCommand.restoreState])}</Text> : null}
                  {arCommand.ackPending ? <View>
                    <Text style={styles.chatNotice}>{t('ar.command.ackPending')}</Text>
                    <Pressable accessibilityRole="button" onPress={() => void arCommand.retryAck()} style={styles.chatRetry}>
                      <Text style={styles.chatSuggestionText}>{t('ar.command.retryAck')}</Text>
                    </Pressable>
                  </View> : null}
                </View> : null}
              </ScrollView>
              <View style={styles.chatComposer}>
                {integratedVoice.mounted && voiceEnabled ? <Suspense fallback={null}><VoiceSessionView {...integratedVoice} /></Suspense> : null}
                {keyboardVisible ? <View style={styles.chatInputRow}>
                  {voice.available ? <Pressable accessibilityRole="button" accessibilityLabel={t('ar.voice.start')}
                    onPress={() => setTestKeyboard(false)} style={styles.sendBtn}>
                    <Ionicons name="mic-outline" size={20} color="#FFFFFF" />
                  </Pressable> : null}
                  <TextInput value={draft} onChangeText={setDraft}
                    accessibilityLabel={t('ar.chatPlaceholder')} placeholder={t('ar.chatPlaceholder')} placeholderTextColor="rgba(255,255,255,0.8)"
                    style={styles.chatInput} underlineColorAndroid="transparent" returnKeyType="send" onSubmitEditing={sendCommand} />
                  <Pressable accessibilityRole="button" accessibilityLabel={t('ar.send')} disabled={!canSendCommand} onPress={sendCommand} style={[styles.sendBtn, !canSendCommand && { opacity: 0.5 }]}>
                    <Ionicons name="send" size={18} color="#FFFFFF" />
                  </Pressable>
                </View> : voice.available ? <>
                  <Text accessibilityLiveRegion="polite" style={styles.voiceStatus}>
                    {t(voice.notice ?? (voice.phase === 'idle' ? 'ar.voice.start' : `ar.voice.${voice.phase}`))}
                  </Text>
                  <View style={styles.voiceControls}>
                    <View style={styles.voiceSide}>
                      {__DEV__ && !inConversation ? <Pressable accessibilityRole="button" accessibilityLabel={t('ar.voice.testKeyboard')}
                        onPress={() => setTestKeyboard(true)} style={styles.voiceAccessory}>
                        <Ionicons name="keypad-outline" size={20} color="#FFFFFF" />
                      </Pressable> : null}
                    </View>
                    <Pressable accessibilityRole="button" accessibilityLabel={t(inConversation ? 'ar.voice.finish' : 'ar.voice.start')}
                      disabled={voice.phase === 'ending' || (!inConversation && (sendingChat || commandBusy))}
                      onPress={voice.microphone} style={styles.voiceButton}>
                      <Ionicons name={inConversation ? 'stop' : 'mic'} size={26} color="#FFFFFF" />
                    </Pressable>
                    <View style={styles.voiceSide}>
                      {!integratedVoiceModel && <Pressable accessibilityRole="button" accessibilityLabel={t(voice.muted ? 'ar.voice.unmute' : 'ar.voice.mute')}
                        onPress={voice.toggleSound} style={styles.voiceAccessory}>
                        <Ionicons name={voice.muted ? 'volume-mute-outline' : 'volume-high-outline'} size={20} color="#FFFFFF" />
                      </Pressable>}
                    </View>
                  </View>
                </> : <Text style={styles.voiceStatus}>{t('ar.voice.unavailable')}</Text>}
              </View>
            </View>
          </KeyboardAvoidingView>
        ) : (
          <View pointerEvents="box-none" style={[styles.arcDock, { paddingBottom: dockBottom }]}>
            {!zoneMenuOpen ? <View pointerEvents="box-none" style={styles.arcStatus}>
              {shadowPointing ? <Text style={styles.arcEmpty}>{t('ar.shadow.pointHint')}</Text> : null}
              {products.isPending ? <ActivityIndicator color="#FFFFFF" /> : null}
              {products.isError ? <Pressable accessibilityRole="button" onPress={() => products.refetch()} style={styles.statusNotice}><Text style={styles.whiteText}>{t('common.errorTitle')} · {t('common.retry')}</Text></Pressable> : null}
              {!products.isPending && !products.isError && displayedSwatches.length === 0 ? (
                <Text style={styles.arcEmpty}>{t(nearby.active ? 'ar.explore.empty' : zoneSwatches.length ? 'ar.filter.empty' : 'ar.noProducts')}</Text>
              ) : null}
              {currentAdded ? <Text style={styles.addedNote} accessibilityLiveRegion="polite">{t('ar.addedSelection')}</Text> : null}
            </View> : null}
            <View testID="ar-current-product" pointerEvents={zoneMenuOpen ? 'none' : 'auto'} aria-hidden={zoneMenuOpen} accessibilityElementsHidden={zoneMenuOpen} importantForAccessibility={zoneMenuOpen ? 'no-hide-descendants' : 'auto'} style={[styles.currentRow, styles.directRow, zoneMenuOpen && { opacity: 0 }]}>
              <View style={styles.productGroup}>
                <Pressable disabled={!currentSwatch} accessibilityRole="button" accessibilityLabel={t('ar.openProduct')} onPress={() => setSheet('product')} style={styles.currentProduct}>
                  {currentSwatch ? (
                    <View style={styles.arcProductCopy}>
                      <Text numberOfLines={1} style={styles.currentName}>{currentSwatch.product.name}</Text>
                      <Text numberOfLines={1} style={styles.arcShadeName}>{currentSwatch.shade.name}
                        {currentSwatch.product.texture ? ` · ${t(`ar.texture.${currentSwatch.product.texture}`)}` : ''}
                      </Text>
                    </View>
                  ) : <Text numberOfLines={1} style={styles.currentName}>{t('ar.arc.pickShade')}</Text>}
                  <Ionicons name="chevron-forward" size={16} color="#FFFFFF" />
                </Pressable>
                <Pressable disabled={!currentSwatch} accessibilityRole="button" accessibilityLabel={t('ar.addThisProduct')} onPress={onAddCurrent} style={styles.arcCart}>
                  <Ionicons name={currentAdded ? 'checkmark' : 'bag-add-outline'} size={23} color="#FFFFFF" />
                </Pressable>
              </View>
              {textureOptions.length > 0 ? <TextureSelect options={textureOptions} value={textureFilter}
                onChange={setTexture} /> : null}
            </View>
            <View pointerEvents={zoneMenuOpen ? 'none' : 'auto'} aria-hidden={zoneMenuOpen} accessibilityElementsHidden={zoneMenuOpen} importantForAccessibility={zoneMenuOpen ? 'no-hide-descendants' : 'auto'} style={zoneMenuOpen ? { opacity: 0 } : undefined}>
            <OpenArcPalette key={JSON.stringify([zone, nearby.active, nearby.anchor?.product.id, nearby.anchor?.shade.id, nearby.direction, textureFilter, familyFilter, careChip])}
              items={displayedSwatches} selected={paletteSelection ?? undefined} label={t('ar.arc.palette')} hint={t('ar.arc.swipe')}
              onVisible={activity.visible}
              recommendedItems={activity.recommendedItems} recommendedLabel={t('ar.arc.recommended')}
              onSelect={({ product, shade }) => {
                if (shadowPointing) setShadowPoint(makeup.eyeshadow?.hexTo === shade.hex ? null : shade.hex);
                else if (careOpen && careSelection?.productId === product.id && careSelection.shadeId === shade.id) clearLipCare();
                else if (!careOpen && selections[zone]?.productId === product.id && selections[zone]?.shadeId === shade.id) clearZone(zone);
                else applyDirect(product, shade, true);
                Haptics.selectionAsync().catch(() => {});
              }} />
            </View>
            <View style={[styles.hubRow, zoneMenuOpen && { marginTop: -zoneWheelRadius(windowWidth) }]}>
              {!zoneMenuOpen && nearby.active && nearby.canRebase ? <Pressable accessibilityRole="button" accessibilityLabel={t('ar.explore.rebase')} onPress={nearby.rebase} style={styles.rebase}>
                <Text style={styles.whiteText}>{t('ar.explore.rebase')}</Text>
              </Pressable> : null}
              {nearby.active ? <ArZoneWheel key="directions" zones={NEARBY_DIRECTIONS} selected={nearby.direction}
                labels={Object.fromEntries(NEARBY_DIRECTIONS.map(d => [d, t(`ar.explore.${d}`)]))}
                directionLabel={t('ar.ui.direction')} hint={t(`ar.explore.${nearby.direction}`)}
                openLabel={t('ar.arc.direction')} closeLabel={t('common.cancel')} onSelect={nearby.setDirection} onOpenChange={setZoneMenuOpen} />
              : <ArZoneWheel key="zones" zones={AR_PAINT_ZONES} selected={zone} labels={Object.fromEntries(AR_PAINT_ZONES.map((z) => [z, t(`ar.zone.${z}` as TranslationKey)]))}
                hint={t('ar.arc.hold')} openHint={t('ar.arc.release')} openLabel={t('ar.arc.zones')} closeLabel={t('common.cancel')} onSelect={chooseZone} onOpenChange={setZoneMenuOpen} />}
              {!zoneMenuOpen ? <Pressable accessibilityRole="button" accessibilityLabel={t('ar.arc.info')} onPress={() => setSheet('info')} style={styles.infoButton}>
                <Ionicons name="information-circle-outline" size={20} color="#FFFFFF" />
              </Pressable> : null}
            </View>
          </View>
        )}
      </SafeAreaView>
      {!isFullscreenAR && sheet ? (
        <ArSheet compact={sheet === 'tools'} title={t(sheet === 'tools' ? 'ar.arc.tools' : sheet === 'product' ? 'ar.openProduct' : 'ar.arc.info')} closeLabel={t('common.cancel')} bottomInset={insets.bottom} onClose={() => setSheet(null)}>
          {sheet === 'tools' ? (
            <ScrollView style={{ maxHeight: windowHeight * 0.55 }} contentContainerStyle={styles.moreModes}>
              <Button label={t('ar.mirror.enter')} icon="expand-outline" variant="secondary" disabled={!liveCamera}
                onPress={() => { setSheet(null); setMirrorMode(true); }} />
              <Button label={t('ar.ui.practice')} icon="brush-outline" variant="secondary"
                onPress={() => { setSheet(null); startPractice(); }} />
              {liveCamera && recorder.available ? <Button label={t(recorder.wanted ? 'ar.rec.stop' : 'ar.rec.start')} icon="videocam-outline" variant="secondary" compact disabled={recorder.state === 'saving'} onPress={recorder.toggle} /> : null}
              {(zoneGap || modified.includes(zone) || (!nearby.supported && zoneHex) ||
                (zone === 'lip' && (careSwatches.length > 0 || displayedFamilies.length > 0)) ||
                (zone === 'foundation' && zoneSwatches.length > 0)) && <Text style={styles.matchTitle}>{currentSwatch
                ? `${t(`ar.zone.${zone}` as TranslationKey)} · ${currentSwatch.product.name}`
                : t(`ar.zone.${zone}` as TranslationKey)}</Text>}
              {zone === 'lip' && (careSwatches.length > 0 || displayedFamilies.length > 0) ? (
                <ScrollView
                  horizontal
                  nestedScrollEnabled
                  showsHorizontalScrollIndicator={false}
                  style={styles.hScroll}
                  contentContainerStyle={styles.filters}>
                  {careSwatches.length > 0 ? (
                    <Chip
                      label={t('ar.chip.lipCare')}
                      selected={careOpen}
                      onPress={() => {
                        setTextureFilter(null);
                        setFamilyFilter(null);
                        if (nearby.active) nearby.leave();
                        setCareChip(careOpen ? null : 'all');
                      }}
                    />
                  ) : null}
                  {!careOpen && displayedFamilies.length ? <View style={styles.filterDivider} /> : null}
                  {!careOpen ? displayedFamilies.map((fm) => (
                    <Chip key={fm} label={t(`ar.family.${fm}` as TranslationKey)} selected={familyFilter === fm}
                      onPress={() => filter(textureFilter, familyFilter === fm ? null : fm, null)} />
                  )) : null}
                  {/* Inside 립케어 only: oil or balm (press again for both). */}
                  {careOpen ? <View style={styles.filterDivider} /> : null}
                  {careOpen
                    ? (['oil', 'balm'] as const).map((k) => (
                        <Chip
                          key={k}
                          label={t(k === 'oil' ? 'ar.care.oil' : 'ar.care.balm')}
                          selected={careChip === k}
                          onPress={() => setCareChip(careChip === k ? 'all' : k)}
                        />
                      ))
                    : null}
                </ScrollView>
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
                        onPress={() => applyDirect(zoneGap.nearest.product, zoneGap.nearest.shade)}
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
                          onPress={() => {
                            const worn =
                              selections.foundation?.productId === m.product.id && selections.foundation?.shadeId === m.shade.id;
                            if (worn) clearZone('foundation');
                            else applyDirect(m.product, m.shade);
                          }}
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
              {zone === 'eyeshadow' && makeup.eyeshadow ? (
                <View style={styles.finishOptions}>
                  <Chip
                    label={t('ar.shadow.point')}
                    selected={shadowPointing}
                    onPress={() => {
                        setShadowPointMode(!shadowPointing);
                        if (!shadowPointing) setSheet(null);
                      }}
                  />
                  {makeup.eyeshadow.hexTo ? (
                    <Chip
                      label={t('ar.shadow.pointOff')}
                      onPress={() => {
                        setShadowPoint(null);
                        setShadowPointMode(false);
                      }}
                    />
                  ) : null}
                  {SHADOW_FINISH_IDS.map((id) => (
                    <Chip
                      key={id}
                      label={t((id === 'glitter' ? 'ar.shadow.glitter' : `ar.texture.${id}`) as TranslationKey)}
                      selected={shadowFinishOf(makeup.eyeshadow) === id}
                      onPress={() => makeup.eyeshadow && patchGeometry('eyeshadow', { shadowFinish: id })}
                    />
                  ))}
                </View>
              ) : null}
              {zone === 'highlighter' && makeup.highlighter ? (
                <>
                  {/* Face type (11-11): auto = the measured shape (oval until measured); a pick sets the regions below. */}
                  <ScrollView
                    horizontal
                    nestedScrollEnabled
                    showsHorizontalScrollIndicator={false}
                    style={styles.hScroll}
                    contentContainerStyle={styles.filters}>
                    <Chip
                      label={
                        faceShape
                          ? t('ar.hlFace.autoWith', { name: hlFaceName(faceShape) })
                          : t('ar.hlFace.auto')
                      }
                      selected={!makeup.highlighter.geometry?.hlStyle && !makeup.highlighter.geometry?.hlFace}
                      onPress={() => patchGeometry('highlighter', { hlFace: undefined, areas: undefined, hlStyle: undefined })}
                    />
                    {HIGHLIGHT_FACES.map((face) => (
                      <Chip
                        key={face}
                        label={hlFaceName(face)}
                        selected={!makeup.highlighter?.geometry?.hlStyle && makeup.highlighter?.geometry?.hlFace === face}
                        onPress={() =>
                          patchGeometry('highlighter', {
                            hlFace: !makeup.highlighter?.geometry?.hlStyle && makeup.highlighter?.geometry?.hlFace === face ? undefined : face,
                            areas: undefined,
                            hlStyle: undefined,
                          })
                        }
                      />
                    ))}
                  </ScrollView>
                  <Text style={styles.noProducts}>
                    {t(`ar.hlFace.tip.${highlighterFaceOf(makeup.highlighter.geometry, faceShape)}` as TranslationKey)}
                  </Text>
                  {/* Regions: exactly what is painted (the face type's set until one is toggled). A style chip below draws its own
                      template instead, so while one is on no region shows as painted; a region or face chip turns the style off. */}
                  <ScrollView
                    horizontal
                    nestedScrollEnabled
                    showsHorizontalScrollIndicator={false}
                    style={styles.hScroll}
                    contentContainerStyle={styles.filters}>
                    {HIGHLIGHTER_AREAS.map((area) => {
                      const painted = effectiveHighlighterAreas(makeup.highlighter?.geometry, faceShape);
                      const styleOn = !!makeup.highlighter?.geometry?.hlStyle;
                      return (
                        <Chip
                          key={area}
                          label={t(`looks.area.${area}` as TranslationKey)}
                          selected={!styleOn && painted.includes(area)}
                          onPress={() => {
                            const patch = highlighterAreaPatch(makeup.highlighter?.geometry, faceShape, area);
                            if (patch) patchGeometry('highlighter', patch);
                          }}
                        />
                      );
                    })}
                  </ScrollView>
                </>
              ) : null}
              {zone === 'highlighter' && makeup.highlighter ? (
                <>
                  <ScrollView
                    horizontal
                    nestedScrollEnabled
                    showsHorizontalScrollIndicator={false}
                    style={styles.hScroll}
                    contentContainerStyle={styles.filters}>
                    <Chip
                      label={t('ar.style.default')}
                      selected={!makeup.highlighter?.geometry?.hlStyle}
                      onPress={() => patchGeometry('highlighter', { hlStyle: undefined })}
                    />
                    {HIGHLIGHTER_STYLE_IDS.map((id) => (
                      <Chip
                        key={id}
                        label={t(`ar.hlStyle.${id}` as TranslationKey)}
                        selected={makeup.highlighter?.geometry?.hlStyle === id}
                        onPress={() => patchGeometry('highlighter', { hlStyle: id })}
                      />
                    ))}
                  </ScrollView>
                  {faceFitHints ? (
                    <Text style={styles.noProducts}>
                      {faceFitHints.map((hint) => t(`ar.faceFit.${hint}` as TranslationKey)).join(' ')}
                    </Text>
                  ) : null}
                </>
              ) : null}
              {/* Shading: the colour alone decides; the jawline and the nose bridge are always painted together. */}
              {zone === 'contour' && makeup.contour ? (
                <>
                  <Text style={styles.noProducts}>{t('ar.contourPlacement.auto')}</Text>
                  {/* Never waits: the default shading is on the screen while the face shape is analysed. */}
                  <Text style={styles.noProducts}>
                    {faceFitStatus === 'personalized' && faceShape
                      ? t('ar.faceShape.result', { name: t(`ar.faceShape.name.${faceShape}` as TranslationKey) }) +
                        ' · ' + t(`ar.faceShape.rule.${faceShape}` as TranslationKey)
                      : t(faceFitStatus === 'fallback' ? 'ar.faceShape.fallback' : faceFitStatus === 'analyzing' ? 'ar.faceShape.analyzing' : 'ar.faceShape.default')}
                  </Text>
                </>
              ) : null}
              {zone === 'eyeliner' && makeup.eyeliner ? (
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
              {!nearby.supported && zoneHex ? (
                <Button multiline label={t('ar.recommendColor')} icon="pricetag-outline"
                  onPress={() => recKey && setRecFor(recKey)} />
              ) : null}
              {(selectionItems.length > 1 || (activeLook && selectionItems.length > 0)) && (
                <Button multiline label={added ? t('looks.viewCart') : t('ar.addSelection')}
                  variant="secondary" icon={added ? 'checkmark' : 'cart-outline'}
                  disabled={selectionItems.length === 0} onPress={onAddSelection} />
              )}
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
              {!nearby.supported && zoneHex ? (
                <Button multiline label={t('ar.similar')} variant="secondary" icon="color-filter-outline"
                  disabled={!zoneSelection} onPress={openRecommendations} />
              ) : null}
            </ScrollView>
          ) : (
            <ScrollView style={{ maxHeight: windowHeight * 0.55 }} contentContainerStyle={styles.sheetContent}>
              {sheet === 'product' ? productDetails : null}
              {showsDemo ? <Text style={styles.matchNote}>{t('ar.demoColors')}</Text> : null}
              {nearby.active ? <Text style={styles.matchNote}>{t('ar.explore.results', { count: displayedSwatches.length })} · {t('ar.explore.basis')}</Text> : null}
              <Text style={styles.disclaimer}>{t('ar.disclaimer')}</Text>
            </ScrollView>
          )}
        </ArSheet>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  overlayScreen: { flex: 1 },
  topbar: { paddingHorizontal: 12, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', minHeight: 52, zIndex: 8 },
  topIcon: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  topIconVisual: { width: 32, height: 32, borderRadius: 16, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(30,22,27,0.46)' },
  cartBadge: { position: 'absolute', top: 1, right: 0, minWidth: 16, paddingHorizontal: 3, borderRadius: 8, backgroundColor: theme.colors.rose, color: '#FFFFFF', fontSize: 9, textAlign: 'center' },
  bottomShade: { position: 'absolute', bottom: 0, left: 0, right: 0, height: '48%' },
  notices: { gap: 10, zIndex: 2, paddingTop: 4 },
  sampleNotice: { alignSelf: 'center', paddingHorizontal: 10, paddingVertical: 4, borderRadius: 12, color: '#FFFFFF', fontSize: 10, backgroundColor: 'rgba(30,22,27,0.6)' },
  coachPill: {
    alignSelf: 'center',
    maxWidth: '88%',
    marginTop: 2,
    backgroundColor: theme.colors.overlay,
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: theme.radius.pill,
  },
  coachPanel: {
    alignSelf: 'center',
    width: '88%',
    marginTop: 2,
    alignItems: 'center',
    gap: 8,
    backgroundColor: theme.colors.overlay,
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderRadius: theme.radius.md,
  },
  coachText: { color: theme.colors.white, fontSize: 12, fontWeight: '600', textAlign: 'center' },
  arcDock: { position: 'absolute', bottom: 0, width: '100%' },
  railArea: { position: 'absolute', right: 12, width: 48, justifyContent: 'center', alignItems: 'center', zIndex: 9 },
  sideControls: { position: 'absolute', width: '100%', paddingHorizontal: 16, height: 226, zIndex: 8 },
  leftTools: { position: 'absolute', left: 16, top: 58, gap: 6, zIndex: 4 },
  sideControl: { width: 44, minHeight: 52, alignItems: 'center', justifyContent: 'center', gap: 3 },
  sideLabel: { fontSize: 10, color: '#FFFFFF', fontWeight: '600', textShadowColor: 'rgba(0,0,0,0.75)', textShadowOffset: { width: 0, height: 1 }, textShadowRadius: 3 },
  sideIcon: { width: 32, height: 32, borderRadius: 16, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(30,22,27,0.5)' },
  selectedTool: { backgroundColor: theme.colors.rose, borderWidth: 1, borderColor: '#FFFFFF' },
  directRow: { paddingHorizontal: 16, justifyContent: 'space-between', gap: 8 },
  productGroup: { flexDirection: 'row', alignItems: 'center', flexShrink: 1, minWidth: 0 },
  arcProductCopy: { flexShrink: 1, minWidth: 0 },
  arcShadeName: { fontSize: 11, color: 'rgba(255,255,255,0.85)' },
  arcCart: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  currentRow: { paddingHorizontal: 40, flexDirection: 'row', justifyContent: 'center', alignItems: 'center', height: AR_PRODUCT_ROW_HEIGHT, flexShrink: 0 },
  currentProduct: { flexShrink: 1, flexDirection: 'row', gap: 5, minHeight: 44, alignItems: 'center' },
  currentName: { flexShrink: 1, color: '#FFFFFF', fontSize: 14, fontWeight: '600' },
  addCurrent: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center', marginLeft: 10 },
  addedNote: { textAlign: 'center', fontSize: 11, color: '#FFFFFF' },
  arcEmpty: { color: '#FFFFFF', fontSize: 12, lineHeight: 18, paddingHorizontal: 24, textAlign: 'center' },
  arcStatus: { position: 'absolute', top: AR_PRODUCT_ROW_HEIGHT + 68, left: 60, right: 60, zIndex: 6 },
  hubRow: { position: 'relative', zIndex: 5 },
  rebase: { position: 'absolute', left: 12, top: 8, maxWidth: '36%', minHeight: 44, borderRadius: 22, borderWidth: 1, borderColor: '#FFFFFF', paddingHorizontal: 10, justifyContent: 'center', zIndex: 6 },
  whiteText: { color: '#FFFFFF', fontSize: 11, fontWeight: '600' },
  infoButton: { position: 'absolute', right: 12, top: 8, width: 44, height: 44, alignItems: 'center', justifyContent: 'center', zIndex: 6 },
  statusNotice: { alignSelf: 'center', padding: 10, minHeight: 44 },
  chatDock: { position: 'absolute', top: 58, bottom: 0, width: '100%', justifyContent: 'flex-end' },
  finishOptions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  moreModes: { padding: 16, gap: 8 },
  sheetContent: { gap: 14, paddingVertical: 16, paddingHorizontal: 4 },
  screen: { flex: 1, backgroundColor: theme.colors.ink },
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
  camera: { flex: 1, backgroundColor: theme.colors.black, overflow: 'hidden' },
  consent: { flexGrow: 1, padding: 28, paddingTop: 100, paddingBottom: 380, alignItems: 'center', justifyContent: 'center', gap: 12, backgroundColor: theme.colors.surface },
  consentTitle: { fontSize: theme.font.h2, fontWeight: '800', color: theme.colors.ink, textAlign: 'center', marginBottom: 6 },
  point: { flexDirection: 'row', gap: 10, alignItems: 'flex-start', alignSelf: 'stretch' },
  pointText: { flex: 1, fontSize: theme.font.body, color: theme.colors.inkMuted, lineHeight: 21, textAlign: 'left' },
  consentBtn: { alignSelf: 'stretch', marginTop: 10 },
  stageActions: { position: 'absolute', top: 160, left: 0, right: 0, flexDirection: 'row', justifyContent: 'center', gap: 8 },
  overlay: { position: 'absolute', top: 0, right: 0, bottom: 0, left: 0, alignItems: 'center', justifyContent: 'center', gap: 10, backgroundColor: 'rgba(0,0,0,0.35)' },
  overlayText: { color: theme.colors.white, fontSize: theme.font.small, fontWeight: '600' },
  noFace: { position: 'absolute', top: 120, left: 16, right: 16, alignItems: 'center', gap: 8, backgroundColor: theme.colors.overlay, padding: 12, borderRadius: theme.radius.md },
  noFaceActions: { flexDirection: 'row', gap: 8 },
  pillBtn: { minHeight: 36, paddingHorizontal: 14, justifyContent: 'center', borderRadius: theme.radius.pill, backgroundColor: 'rgba(255,255,255,0.18)' },
  pillBtnText: { color: theme.colors.white, fontSize: theme.font.small, fontWeight: '700' },
  hintPill: { position: 'absolute', top: 112, alignSelf: 'center', backgroundColor: theme.colors.overlay, paddingHorizontal: 14, paddingVertical: 8, borderRadius: theme.radius.pill },
  hintText: { color: theme.colors.white, fontSize: theme.font.small, fontWeight: '600', textAlign: 'center' },
  liveBadge: { position: 'absolute', top: 96, left: 12, flexDirection: 'row', alignItems: 'center', gap: 6, backgroundColor: theme.colors.overlay, paddingHorizontal: 10, paddingVertical: 5, borderRadius: theme.radius.pill },
  liveDot: { width: 7, height: 7, borderRadius: 4, backgroundColor: '#4ADE80' },
  liveText: { color: theme.colors.white, fontSize: 11, fontWeight: '600' },
  recDot: { backgroundColor: '#F87171' },
  recordBtn: { position: 'absolute', left: 14, width: 44, height: 44, borderRadius: 22, alignItems: 'center', justifyContent: 'center', backgroundColor: theme.colors.overlay },
  recordDot: { width: 18, height: 18, borderRadius: 9, backgroundColor: '#F87171' },
  recordStop: { width: 16, height: 16, borderRadius: 3, backgroundColor: theme.colors.white },
  compareLabel: { position: 'absolute', top: 96, paddingHorizontal: 9, paddingVertical: 5, borderRadius: theme.radius.pill, backgroundColor: theme.colors.overlay },
  beforeLabel: { left: 12 },
  afterLabel: { right: 12 },
  compareLabelText: { color: theme.colors.white, fontSize: 11, fontWeight: '800' },
  splitLine: { position: 'absolute', top: 0, bottom: 0, left: '50%', width: 2, marginLeft: -1, backgroundColor: 'rgba(255,255,255,0.9)' },
  warnBanner: { marginHorizontal: 16, fontSize: 12, fontWeight: '600', color: theme.colors.warning },
  matchCard: { marginHorizontal: 16, padding: 10, gap: 4, alignItems: 'flex-start', borderRadius: theme.radius.md, backgroundColor: theme.colors.roseSoft },
  matchTitle: { fontSize: 11, fontWeight: '800', color: theme.colors.roseDark },
  matchName: { fontSize: theme.font.small, fontWeight: '700', color: theme.colors.ink },
  matchNote: { fontSize: 12, color: theme.colors.inkMuted, lineHeight: 17 },
  fitPanel: { marginHorizontal: 16, padding: 10, gap: 8, alignItems: 'flex-start', borderRadius: theme.radius.md, backgroundColor: theme.colors.roseSoft },
  revertRow: { marginHorizontal: 16, alignItems: 'flex-start' },
  panel: { flexGrow: 0, backgroundColor: theme.colors.surface, borderTopLeftRadius: theme.radius.lg, borderTopRightRadius: theme.radius.lg, marginTop: 10, paddingTop: 14, paddingBottom: 12, gap: 10 },
  hScroll: { flexGrow: 0 },
  lookBanner: { marginHorizontal: 16, fontSize: 12, fontWeight: '700', color: theme.colors.rose },
  lookFinishCard: {
    marginHorizontal: 16,
    paddingHorizontal: 10,
    paddingTop: 6,
    paddingBottom: 4,
    gap: 2,
    borderRadius: theme.radius.md,
    backgroundColor: 'rgba(255,255,255,0.92)',
  },
  lookFinishHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  lookFinishTitle: { flex: 1, fontSize: 12, fontWeight: '800', color: theme.colors.ink },
  lookFinishPct: { fontSize: 11, fontWeight: '700', color: theme.colors.rose },
  filters: { gap: 8, paddingHorizontal: 16, paddingBottom: 10, alignItems: 'center' },
  filterDivider: { width: 1, height: 20, backgroundColor: theme.colors.border, marginHorizontal: 2 },
  productCard: { marginHorizontal: 16, flexDirection: 'row', gap: 10, alignItems: 'flex-start' },
  productImage: { width: 56, height: 56, borderRadius: theme.radius.sm },
  productCopy: { flex: 1, gap: 4 },
  productLinks: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  disclaimer: { marginHorizontal: 16, fontSize: 11, lineHeight: 16, color: theme.colors.inkFaint },
  foundBox: { marginHorizontal: 16, gap: 6 },
  foundTitle: { fontSize: 12, fontWeight: '800', color: theme.colors.ink },
  foundNote: { fontSize: 11, lineHeight: 16, color: theme.colors.inkMuted },
  foundChips: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  actions: { flexDirection: 'row', gap: 10, paddingHorizontal: 16 },
  noProducts: { marginHorizontal: 16, fontSize: theme.font.small, color: theme.colors.inkMuted },
  modeRow: { flexDirection: 'row', alignItems: 'center', height: 44, paddingHorizontal: 1 },
  modeBackground: { position: 'absolute', left: 0, right: 0, top: 7, bottom: 7, borderRadius: 20, backgroundColor: 'rgba(38,28,33,0.54)', borderWidth: 1, borderColor: 'rgba(255,255,255,0.72)' },
  modeHit: { minHeight: 44, justifyContent: 'center', borderRadius: 20, ...(Platform.OS === 'web' ? { outlineWidth: 0 } : {}) },
  modeTab: { alignItems: 'center', justifyContent: 'center', paddingHorizontal: 13, height: 28, borderRadius: 16, overflow: 'hidden', borderWidth: 1, borderColor: 'transparent' },
  modeTabActive: { backgroundColor: theme.colors.rose },
  modeTabFocused: { borderColor: '#FFFFFF' },
  modeText: { fontSize: 11, fontWeight: '600', color: '#FFFFFF' },
  modeTextActive: { color: theme.colors.white },
  chat: { flexShrink: 1 },
  chatMirror: { position: 'absolute', top: 0, left: 16, width: 44, minHeight: 52, alignItems: 'center', justifyContent: 'center', gap: 3 },
  chatHistory: { flex: 1 },
  chatHistoryContent: { flexGrow: 1, justifyContent: 'flex-end', paddingHorizontal: 18, paddingBottom: 12, gap: 8 },
  chatComposer: { minHeight: 88, flexShrink: 0, paddingTop: 4, paddingHorizontal: 18 },
  voiceStatus: { color: '#FFFFFF', fontSize: 13, textAlign: 'center', alignSelf: 'center', backgroundColor: 'rgba(30,22,27,0.65)', borderRadius: 10, paddingHorizontal: 10, paddingVertical: 2 },
  voiceControls: { flexDirection: 'row', justifyContent: 'center', alignItems: 'center', gap: 16, marginTop: 4 },
  voiceSide: { width: 44 },
  voiceAccessory: { width: 44, height: 44, borderRadius: 22, backgroundColor: 'rgba(30,22,27,0.6)', alignItems: 'center', justifyContent: 'center' },
  voiceButton: { width: 56, height: 56, borderRadius: 28, backgroundColor: theme.colors.rose, alignItems: 'center', justifyContent: 'center' },
  chatMessages: { gap: 10, paddingVertical: 2 },
  chatUserBubble: { alignSelf: 'flex-end', maxWidth: '86%', paddingHorizontal: 16, paddingVertical: 8, backgroundColor: '#F0DCE3', borderRadius: 22, borderBottomRightRadius: 5 },
  chatReplyRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 7, paddingRight: 12 },
  chatReplyBubble: { flexShrink: 1, paddingHorizontal: 14, paddingVertical: 8, backgroundColor: 'rgba(255,248,250,0.93)', borderRadius: 18, borderBottomLeftRadius: 5 },
  chatMessageText: { fontSize: 14, lineHeight: 21, color: theme.colors.ink },
  chatStatus: { gap: 6 },
  chatNotice: { fontSize: 12, lineHeight: 18, color: '#FFFFFF', backgroundColor: 'rgba(30,22,27,0.65)', borderRadius: 12, padding: 8 },
  panelFold: { alignSelf: 'center', width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  chatRetry: { alignSelf: 'flex-start', minHeight: 44, justifyContent: 'center', paddingHorizontal: 12 },
  chatSuggestions: { flexGrow: 0, marginHorizontal: -18 },
  chatExamples: { gap: 10, paddingHorizontal: 24, paddingVertical: 2 },
  chatSuggestion: { minHeight: 44, borderRadius: 22, borderWidth: 1, borderColor: 'rgba(255,255,255,0.8)', backgroundColor: 'rgba(30,22,27,0.26)', justifyContent: 'center', paddingHorizontal: 16 },
  chatSuggestionText: { color: '#FFFFFF', fontSize: 13, fontWeight: '500' },
  chatInputRow: { flexDirection: 'row', alignItems: 'center', borderWidth: 1, borderColor: 'rgba(255,255,255,0.85)', backgroundColor: 'rgba(30,22,27,0.4)', borderRadius: 28, padding: 3 },
  chatInput: { flex: 1, minWidth: 0, minHeight: 44, paddingHorizontal: 14, paddingVertical: 10, fontSize: 14, color: '#FFFFFF' },
  sendBtn: { width: 44, height: 44, borderRadius: 22, backgroundColor: theme.colors.rose, alignItems: 'center', justifyContent: 'center' },
});
