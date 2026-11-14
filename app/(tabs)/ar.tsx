import Ionicons from '@expo/vector-icons/Ionicons';
import { uuid } from 'expo';
import { useCameraPermissions } from 'expo-camera';
import * as Haptics from 'expo-haptics';
import { LinearGradient } from 'expo-linear-gradient';
import * as WebBrowser from 'expo-web-browser';
import { useFocusEffect, useLocalSearchParams, useNavigation, useRouter } from 'expo-router';
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
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
  type GestureResponderEvent,
} from 'react-native';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import { ArFaceView, type LightHint } from '@/components/ar/ArFaceView';
import { ArSheet } from '@/components/ar/ArSheet';
import { ArZoneWheel, zoneWheelRadius } from '@/components/ar/ArZoneWheel';
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
  highlighterFaceOf,
  toggleHighlighterArea,
} from '@/lib/arFacePalette';
import { HIGHLIGHTER_STYLE_IDS, type FaceFitHint, type FaceFitStatus, type FaceShape } from '@/lib/faceFit';
import { COLOR_FAMILIES, colorFamily, type ColorFamily } from '@/lib/colorFamily';
import { arChatRoute } from '@/lib/arChatRoute';
import { adjustMakeupFromChat } from '@/lib/arChatAdjust';
import { isSafeExternalUrl } from '@/lib/externalLink';
import { formatKRW } from '@/lib/format';
import { LINER_LOOK_IDS, LINER_LOOKS, matchingLinerLook } from '@/lib/linerLooks';
import { SHADOW_FINISH_IDS, shadowFinishOf } from '@/lib/shadowFinishes';
import { findColorGaps, recommendShades, type LookLine } from '@/lib/colorGaps';
import { guideMessage } from '@/lib/drawGuide';
import { buildGuideSteps, guideText } from '@/lib/lookGuide';
import { practiceDrawStep, practiceZones, revealedMakeup, visit } from '@/lib/practice';
import { useArRecording } from '@/hooks/useArRecording';
import { useArRouteSelection } from '@/hooks/useArRouteSelection';
import { useNearbyExploration } from '@/hooks/useNearbyExploration';
import { useArCommand } from '@/hooks/useArCommand';
import { MIN_TONE_CONF, rankFoundationShades, type SkinTone } from '@/lib/foundationMatch';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import { useTryOnProducts } from '@/lib/queries';
import { parseFlag, parseId, productHref, recommendationsHref } from '@/lib/routes';
import { useCartStore } from '@/store/cartStore';
import { isLipBaseCare, LIP_TEXTURE_CHIPS, lipCareKind, lipTextureChip } from '@/lib/lipCare';
import { AR_PAINT_ZONES, arPaintMakeup, isArPaintZone, useMakeupStore } from '@/store/makeupStore';
import { useSettingsStore } from '@/store/settingsStore';
import type { HighlightFace, MakeupZone, Texture } from '@/types';

type Mode = 'direct' | 'chat';

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
  const { t, language } = useI18n();
  const { height: windowHeight, width: windowWidth } = useWindowDimensions();
  const dockBottom = Math.max(24, insets.bottom);
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
  const [mode, setMode] = useState<Mode>('direct');
  const [focusedMode, setFocusedMode] = useState<Mode | null>(null);
  const [sheet, setSheet] = useState<'tools' | 'product' | 'info' | null>(null);
  const [zoneMenuOpen, setZoneMenuOpen] = useState(false);
  const [addedShade, setAddedShade] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [chatNote, setChatNote] = useState<TranslationKey | null>(null);
  const [chatRequest, setChatRequest] = useState<{ text: string; route: ReturnType<typeof arChatRoute> } | null>(null);
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
    activeLook,
    heroZones,
    stepOrder,
    modified,
    applyShade,
    clearZone,
    clearLipCare,
    patchGeometry,
    setIntensity,
    revertZone,
    fit,
    endFit,
    clearLookMascara,
  } = useMakeupStore();
  const [blushTrackW, setBlushTrackW] = useState(0);
  const blushTrackWRef = useRef(0);
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
  const nearby = useNearbyExploration(
    tryOnProducts, zone, selectedTryOn, textureFilter,
    JSON.stringify([routeProductId, routeShadeId, activeLook?.id])
  );
  // Filter chips: only textures / color families present in this zone; families for lips only.
  const textureOptions = useMemo(
    () =>
      zone === 'blush' || zone === 'eyeshadow' || zone === 'foundation' || zone === 'highlighter' || zone === 'contour'
        ? []
        : zone === 'lip'
          ? // Four finish chips: velvet sits with matte, satin with cream, sheer with glossy.
            LIP_TEXTURE_CHIPS.filter((tx) => zoneSwatches.some(({ product }) => lipTextureChip(product.texture) === tx))
          : TEXTURES.filter((tx) => zoneSwatches.some(({ product }) => product.texture === tx)),
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
  const displayedSwatches = nearby.active ? nearby.groups[nearby.direction] : visibleSwatches;
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
  const rendererId = useMemo(() => [arKey, rendererMounted, uuid.v4()].join(':'), [arKey, rendererMounted]);
  const commandEnabled = rendererMounted && status === 'tracking' && !fit && !practice && !compare && mode === 'chat';
  const arCommand = useArCommand({ active: cameraActive, enabled: commandEnabled, activeZone: zone, locale: language, rendererId,
    visibleZones: practice && activeLook && !peek ? practice.visited : null });
  const commandBusy = arCommand.state === 'interpreting' || arCommand.state === 'proposed' || arCommand.state === 'applying' || arCommand.restoreState === 'pending';
  const draftRoute = arChatRoute(draft);
  const localChatEnabled = !fit && !practice && !compare && mode === 'chat';
  const canSendCommand = !!draft.trim() &&
    (draftRoute === 'server' ? commandEnabled && !commandBusy : localChatEnabled);
  const submittedDraft = useRef<string | null>(null);
  useEffect(() => { submittedDraft.current = null; }, [draft]);
  const sendCommand = () => {
    const text = draft.trim();
    if (!canSendCommand || submittedDraft.current === text) return;
    submittedDraft.current = text;
    const route = arChatRoute(text);
    setChatRequest({ text, route });
    if (route === 'server') {
      setChatNote(null);
      void arCommand.send(text).finally(() => {
        if (submittedDraft.current === text) submittedDraft.current = null;
      });
      return;
    }
    if (route === 'clarification') {
      setChatNote('ar.chatClarify');
      return;
    }
    // Local commands are user edits: the Store invalidates any outstanding AI proposal.
    const result = adjustMakeupFromChat(text, tryOnProducts, useMakeupStore.getState().makeup);
    if (result.kind === 'shade') {
      applyShade(result.product, result.shade);
      setZone(result.zone);
      setChatNote('ar.chatAppliedShade');
    } else if (result.kind === 'intensity') {
      setIntensity(result.zone, result.intensity);
      setZone(result.zone);
      setChatNote('ar.chatAppliedIntensity');
    } else if (result.kind === 'geometry') {
      patchGeometry(result.zone, result.geometry);
      setZone(result.zone);
      setChatNote('ar.chatAppliedGeometry');
    } else {
      setChatNote('ar.chatNoMatch');
    }
    setDraft('');
  };

  const onAllow = async () => {
    setCameraConsent(true);
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

  const backToProduct = () => {
    if (router.canGoBack()) router.back();
    else if (routeProductId) router.push(productHref(routeProductId, routeShadeId));
  };

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
    if (!isFullscreenAR) return;
    const sub = BackHandler.addEventListener('hardwareBackPress', () => {
      setMirrorMode(false);
      return true;
    });
    return () => sub.remove();
  }, [isFullscreenAR, setMirrorMode]);

  useFocusEffect(
    useCallback(() => {
      navigation.setOptions({ tabBarStyle: HIDDEN_TAB_BAR_STYLE });
      return () => {
        setSheet(null);
        setAddedShade(null);
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
          renderCommand={arCommand.renderCommand}
          onRenderResult={arCommand.onRenderResult}
          compare={compare}
          guide={guide}
          fillPreview
          onStatus={setStatus}
          onLightHint={setLightHint}
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
    setTextureFilter(null);
    setFamilyFilter(null);
    setCareChip(null);
  };
  const onAddCurrent = () => {
    if (!selectedTryOn) return;
    addToCart({ productId: selectedTryOn.product.id, shadeId: selectedTryOn.shade.id, ...(activeLook ? { addedFromLookId: activeLook.id } : {}) });
    setAddedShade(`${selectedTryOn.product.id}:${selectedTryOn.shade.id}`);
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
  };
  const currentAdded = !!selectedTryOn && addedShade === `${selectedTryOn.product.id}:${selectedTryOn.shade.id}`;
  const explorationControls = nearby.supported ? (
    <NearbyExplorer
      active={nearby.active}
      canEnter={nearby.canEnter}
      anchor={nearby.anchor}
      direction={nearby.direction}
      counts={{
        similar: nearby.groups.similar.length,
        lighter: nearby.groups.lighter.length,
        darker: nearby.groups.darker.length,
        muted: nearby.groups.muted.length,
        vivid: nearby.groups.vivid.length,
      }}
      canGoBack={nearby.canGoBack}
      onEnter={() => { setCareChip(null); nearby.enter(); }}
      onLeave={nearby.leave}
      onDirection={nearby.setDirection}
      onBack={nearby.back}
      onApplyAnchor={() => {
        if (nearby.anchor) applyShade(nearby.anchor.product, nearby.anchor.shade);
      }}
    />
  ) : null;
  const notices = (
    <View style={styles.notices}>
        {showsDemo ? <Text style={styles.sampleNotice}>{t('ar.demoColors')}</Text> : null}
        {activeLook && !fit ? (
          <Text style={styles.lookBanner} numberOfLines={1}>
            {t(modified.length > 0 ? 'ar.lookModified' : 'ar.lookApplied', { title: activeLook.title })}
          </Text>
        ) : null}
        {fromVideo ? <Text style={styles.warnBanner}>{t('videoAr.notice')}</Text> : null}
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
  const productDetails = selectedTryOn ? (
    <View style={styles.productCard}>
      <ProductImage
        uri={selectedTryOn.product.imageUrl}
        category={selectedTryOn.product.category}
        style={styles.productImage}
        recyclingKey={selectedTryOn.product.id}
        compact
      />
      <View style={styles.productCopy}>
        {nearby.active ? <Text style={styles.matchTitle}>{t('ar.explore.preview')}</Text> : null}
        <Text style={styles.matchName} numberOfLines={2}>
          {selectedTryOn.product.brand} {selectedTryOn.product.name}
        </Text>
        <Text style={styles.matchNote} numberOfLines={1}>
          {selectedTryOn.shade.name}
          {selectedTryOn.product.priceKRW > 0 ? ` · ${formatKRW(selectedTryOn.product.priceKRW)}` : ''}
        </Text>
        {nearby.active && nearby.canRebase ? (
          <Button label={t('ar.explore.rebase')} icon="search-outline" compact variant="secondary" onPress={() => { nearby.rebase(); setSheet(null); }} />
        ) : null}
        {selectedTryOn.shade.measureMethod === 'estimated' ? (
          <Text style={styles.foundNote}>{t('ar.shadeEstimated')}</Text>
        ) : null}
        <View style={styles.productLinks}>
          <Chip
            label={t('ar.openProduct')}
            onPress={() =>
              router.push({
                pathname: '/product/[id]',
                params: { id: selectedTryOn.product.id, shade: selectedTryOn.shade.id },
              })
            }
          />
          {isSafeExternalUrl(selectedTryOn.product.sourceUrl) ? (
            <Chip
              label={t('ar.openStore')}
              onPress={() => WebBrowser.openBrowserAsync(selectedTryOn.product.sourceUrl!)}
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
        ) : (
          <ScrollView
            nestedScrollEnabled
            keyboardShouldPersistTaps="handled"
            style={[styles.exploreScroll, { maxHeight: windowHeight * 0.55 }]}
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
                    setCareChip(null);
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

            <View style={styles.toolActions}>
              {liveCamera ? <Button label={t('ar.mirror.enter')} icon="expand-outline" variant="secondary" compact onPress={() => { setSheet(null); setMirrorMode(true); }} /> : null}
              {liveCamera && recorder.available ? <Button label={t(recorder.wanted ? 'ar.rec.stop' : 'ar.rec.start')} icon="videocam-outline" variant="secondary" compact disabled={recorder.state === 'saving'} onPress={recorder.toggle} /> : null}
            </View>
            {currentIntensity !== undefined && !['blush', 'foundation', 'highlighter', 'contour'].includes(zone) ? (
              <View style={styles.foundBox}>
                <Text style={styles.foundTitle}>{t('ar.intensity')} · {Math.round(currentIntensity * 100)}%</Text>
                <CoverageBar value={currentIntensity} labels={{ title: t('ar.intensity'), low: t('ar.arc.light'), high: t('ar.arc.strong') }} onChange={(value) => setIntensity(zone, value)} />
              </View>
            ) : null}
            {products.isError ? (
              <View style={styles.inlineRow}>
                <Text style={styles.noProducts}>{t('common.errorTitle')}</Text>
                <Button label={t('common.retry')} variant="ghost" compact onPress={() => products.refetch()} />
              </View>
            ) : zoneSwatches.length === 0 && !products.isPending ? (
              <Text style={styles.noProducts}>{t('ar.noProducts')}</Text>
            ) : null}
            {textureOptions.length + displayedFamilies.length > 1 || !!textureFilter || (zone === 'lip' && careSwatches.length > 0) ? (
              <ScrollView
                horizontal
                nestedScrollEnabled
                showsHorizontalScrollIndicator={false}
                style={styles.hScroll}
                contentContainerStyle={styles.filters}>
                <Chip
                  label={t(nearby.active ? 'ar.explore.allTextures' : 'ar.filter.all')}
                  selected={!textureFilter && !careOpen && (nearby.active || !familyFilter)}
                  onPress={() => {
                    setTextureFilter(null);
                    setCareChip(null);
                    if (!nearby.active) setFamilyFilter(null);
                  }}
                />
                {textureOptions.map((tx) => (
                  <Chip
                    key={tx}
                    label={t(`ar.texture.${tx}` as TranslationKey)}
                    selected={textureFilter === tx && !careOpen}
                    onPress={() => {
                      setCareChip(null);
                      setTextureFilter(textureFilter === tx ? null : tx);
                    }}
                  />
                ))}
                {zone === 'lip' && careSwatches.length > 0 ? (
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
                    onPress={() => setFamilyFilter(familyFilter === fm ? null : fm)} />
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
            {!nearby.active && zoneSwatches.length > 0 && visibleSwatches.length === 0 ? (
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
                const selected = careOpen
                  ? careSelection?.productId === product.id && careSelection?.shadeId === shade.id
                  : selections[zone]?.productId === product.id && selections[zone]?.shadeId === shade.id;
                return (
                  <Pressable
                    key={`${product.id}-${shade.id}`}
                    onPress={() => {
                      // Pressing the worn shade again takes it off (the bare lip / face shows); another shade replaces it.
                      if (selected) {
                        if (careOpen) clearLipCare();
                        else clearZone(zone);
                      } else {
                        applyShade(product, shade);
                      }
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

            {selectedTryOn ? (
              <View style={styles.productCard}>
                <ProductImage
                  uri={selectedTryOn.product.imageUrl}
                  category={selectedTryOn.product.category}
                  style={styles.productImage}
                  recyclingKey={selectedTryOn.product.id}
                  compact
                />
                <View style={styles.productCopy}>
                  <Text style={styles.matchName} numberOfLines={2}>
                    {selectedTryOn.product.brand} {selectedTryOn.product.name}
                  </Text>
                  <Text style={styles.matchNote} numberOfLines={1}>
                    {selectedTryOn.shade.name}
                    {selectedTryOn.product.priceKRW > 0 ? ` · ${formatKRW(selectedTryOn.product.priceKRW)}` : ''}
                  </Text>
                  {zone === 'lip' && selectedTryOn.product.texture ? (
                    <Text style={styles.foundNote} numberOfLines={1}>
                      {t('ar.textureLabel')}: {t(`ar.texture.${selectedTryOn.product.texture}` as TranslationKey)}
                    </Text>
                  ) : null}
                  {selectedTryOn.shade.measureMethod === 'estimated' ? (
                    <Text style={styles.foundNote}>{t('ar.shadeEstimated')}</Text>
                  ) : null}
                  <View style={styles.productLinks}>
                    <Chip
                      label={t('ar.openProduct')}
                      onPress={() =>
                        router.push({
                          pathname: '/product/[id]',
                          params: { id: selectedTryOn.product.id, shade: selectedTryOn.shade.id },
                        })
                      }
                    />
                    {isSafeExternalUrl(selectedTryOn.product.sourceUrl) ? (
                      <Chip
                        label={t('ar.openStore')}
                        onPress={() => WebBrowser.openBrowserAsync(selectedTryOn.product.sourceUrl!)}
                      />
                    ) : null}
                  </View>
                </View>
              </View>
            ) : null}

            {zone === 'lip' && selectedCare ? (
              <View style={styles.productCard}>
                <ProductImage
                  uri={selectedCare.product.imageUrl}
                  category={selectedCare.product.category}
                  style={styles.productImage}
                  recyclingKey={selectedCare.product.id}
                  compact
                />
                <View style={styles.productCopy}>
                  <Text style={styles.matchName} numberOfLines={2}>
                    {selectedCare.product.brand} {selectedCare.product.name}
                  </Text>
                  <Text style={styles.matchNote} numberOfLines={1}>
                    {t(lipCareKind(selectedCare.product) === 'oil' ? 'ar.care.oil' : 'ar.care.balm')}
                    {selectedTryOn ? ` · ${t('ar.care.over')}` : ''}
                    {selectedCare.product.priceKRW > 0 ? ` · ${formatKRW(selectedCare.product.priceKRW)}` : ''}
                  </Text>
                  <View style={styles.productLinks}>
                    <Chip
                      label={t('ar.openProduct')}
                      onPress={() =>
                        router.push({
                          pathname: '/product/[id]',
                          params: { id: selectedCare.product.id, shade: selectedCare.shade.id },
                        })
                      }
                    />
                  </View>
                </View>
              </View>
            ) : null}

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
                        onPress={() => {
                          const worn =
                            selections.foundation?.productId === m.product.id && selections.foundation?.shadeId === m.shade.id;
                          if (worn) clearZone('foundation');
                          else applyShade(m.product, m.shade);
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
            {(zone === 'highlighter' && makeup.highlighter) || (zone === 'contour' && makeup.contour) ? (
              <View style={styles.foundBox}>
                <CoverageBar
                  value={zone === 'highlighter' ? makeup.highlighter!.intensity : makeup.contour!.intensity}
                  labels={{ title: t('ar.intensity'), low: t('ar.light'), high: t('ar.bold') }}
                  onChange={(v) => setIntensity(zone, v)}
                />
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
                        onPress={() =>
                          patchGeometry('highlighter', {
                            // From a style: back to the face-type layout with this region on. Otherwise: on / off.
                            areas: styleOn && painted.includes(area) ? painted : toggleHighlighterArea(painted, area),
                            hlStyle: undefined,
                          })
                        }
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
              {!nearby.supported ? (
                <Button
                  label={t('ar.recommendColor')}
                  icon="pricetag-outline"
                  disabled={!zoneHex}
                  onPress={() => recKey && setRecFor(recKey)}
                  style={{ flex: 1 }}
                />
              ) : null}
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
            {!nearby.supported ? (
              <View style={styles.actions}>
                <Button
                  label={t('ar.similar')}
                  variant="secondary"
                  icon="color-filter-outline"
                  disabled={!zoneSelection}
                  onPress={openRecommendations}
                />
              </View>
            ) : null}
            {activeLook ? (
              <Button
                label={t('ar.practice.start')}
                icon="brush-outline"
                variant="secondary"
                onPress={() => { setSheet(null); startPractice(); }}
                style={styles.practiceBtn}
              />
            ) : null}
          </ScrollView>
        )}
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
            onPress={() => { if (isFullscreenAR) setMirrorMode(false); else if (router.canGoBack()) router.back(); else router.replace('/(tabs)'); }}>
            <View style={styles.topIconVisual}><Ionicons name="chevron-back" size={20} color="#FFFFFF" /></View>
          </Pressable>
          {!isFullscreenAR && !practicing && !fit ? (
            <View style={styles.modeRow}>
              <View pointerEvents="none" style={styles.modeBackground} />
              {(['direct', 'chat'] as const).map((m) => (
                <Pressable key={m} accessibilityRole="tab" accessibilityState={{ selected: mode === m }}
                  onFocus={() => setFocusedMode(m)} onBlur={() => setFocusedMode(null)}
                  onPress={() => { setSheet(null); setMode(m); }} style={styles.modeHit}>
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
        ) : fit || practicing ? (
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
                <Pressable disabled={!selectedTryOn} accessibilityRole="button" accessibilityLabel={t('ar.openProduct')} onPress={() => setSheet('product')} style={styles.currentProduct}>
                  <Text numberOfLines={1} style={styles.currentName}>{selectedTryOn ? `${t(`ar.zone.${zone}` as TranslationKey)} · ${selectedTryOn.shade.name}` : t('ar.arc.pickShade')}</Text>
                  <Ionicons name="chevron-forward" size={16} color="#FFFFFF" />
                </Pressable>
                <Pressable disabled={!selectedTryOn} accessibilityRole="button" accessibilityLabel={t('ar.addThisProduct')} onPress={onAddCurrent} style={styles.addCurrent}>
                  <Ionicons name={currentAdded ? 'checkmark' : 'bag-add-outline'} size={23} color="#FFFFFF" />
                </Pressable>
              </View>
              <ScrollView style={styles.chatHistory} contentContainerStyle={styles.chatHistoryContent} keyboardShouldPersistTaps="handled" showsVerticalScrollIndicator={false}>
                {currentAdded ? <Text style={styles.addedNote} accessibilityLiveRegion="polite">{t('ar.addedSelection')}</Text> : null}
                {chatRequest ? (
                  <View style={styles.chatMessages}>
                    <View style={styles.chatUserBubble}><Text style={styles.chatMessageText}>{chatRequest.text}</Text></View>
                    {chatNote || (chatRequest.route === 'server' && arCommand.state !== 'idle') ? (
                      <View style={styles.chatReplyRow}>
                        <Ionicons name="chatbubble-ellipses" size={24} color="#F0DCE3" />
                        <View style={styles.chatReplyBubble}>
                          <Text style={styles.chatMessageText} accessibilityLiveRegion="polite">
                            {chatNote ? t(chatNote) : arCommand.state !== 'idle' ? arCommand.message || t(AR_COMMAND_STATUS[arCommand.state]) : ''}
                          </Text>
                        </View>
                      </View>
                    ) : null}
                  </View>
                ) : (
                  <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.chatSuggestions} contentContainerStyle={styles.chatExamples} keyboardShouldPersistTaps="handled">
                    {CHAT_EXAMPLES.map(({ label, request }) => (
                      <Pressable key={request} accessibilityRole="button" accessibilityLabel={t(request)} onPress={() => { submittedDraft.current = null; setDraft(t(request)); }} style={styles.chatSuggestion}>
                        <Text style={styles.chatSuggestionText}>{t(label)}</Text>
                      </Pressable>
                    ))}
                  </ScrollView>
                )}
                {(draftRoute === 'server' && !commandEnabled && !commandBusy) || arCommand.restoreState !== 'idle' || arCommand.ackPending ? <View style={styles.chatStatus}>
                  {draftRoute === 'server' && !commandEnabled && !commandBusy ? <Text style={styles.chatNotice}>{t('ar.command.unavailable')}</Text> : null}
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
                <View style={styles.chatInputRow}>
                  <TextInput value={draft} onChangeText={(text) => { submittedDraft.current = null; setDraft(text); }}
                    accessibilityLabel={t('ar.chatPlaceholder')} placeholder={t('ar.chatPlaceholder')} placeholderTextColor="rgba(255,255,255,0.8)"
                    style={styles.chatInput} underlineColorAndroid="transparent" returnKeyType="send" onSubmitEditing={sendCommand} />
                  <Pressable accessibilityRole="button" accessibilityLabel={t('ar.send')} disabled={!canSendCommand} onPress={sendCommand} style={[styles.sendBtn, !canSendCommand && { opacity: 0.5 }]}>
                    <Ionicons name="send" size={18} color="#FFFFFF" />
                  </Pressable>
                </View>
              </View>
            </View>
          </KeyboardAvoidingView>
        ) : (
          <View pointerEvents="box-none" style={[styles.arcDock, { paddingBottom: dockBottom }]}>
            {!zoneMenuOpen ? <View pointerEvents="box-none" style={styles.arcStatus}>
              {products.isPending ? <ActivityIndicator color="#FFFFFF" /> : null}
              {products.isError ? <Pressable accessibilityRole="button" onPress={() => products.refetch()} style={styles.statusNotice}><Text style={styles.whiteText}>{t('common.errorTitle')} · {t('common.retry')}</Text></Pressable> : null}
              {!products.isPending && !products.isError && displayedSwatches.length === 0 ? (
                <Text style={styles.arcEmpty}>{t(nearby.active ? 'ar.explore.empty' : zoneSwatches.length ? 'ar.filter.empty' : 'ar.noProducts')}</Text>
              ) : null}
              {currentAdded ? <Text style={styles.addedNote} accessibilityLiveRegion="polite">{t('ar.addedSelection')}</Text> : null}
            </View> : null}
            <View testID="ar-current-product" pointerEvents={zoneMenuOpen ? 'none' : 'auto'} aria-hidden={zoneMenuOpen} accessibilityElementsHidden={zoneMenuOpen} importantForAccessibility={zoneMenuOpen ? 'no-hide-descendants' : 'auto'} style={[styles.currentRow, zoneMenuOpen && { opacity: 0 }]}>
              <Pressable disabled={!selectedTryOn} accessibilityRole="button" accessibilityLabel={t('ar.openProduct')} onPress={() => setSheet('product')} style={styles.currentProduct}>
                <Text numberOfLines={1} style={styles.currentName}>{selectedTryOn ? `${selectedTryOn.shade.name}${selectedTryOn.product.texture ? ` · ${t(`ar.texture.${selectedTryOn.product.texture}`)}` : ''}` : t('ar.arc.pickShade')}</Text>
                <Ionicons name="chevron-forward" size={16} color="#FFFFFF" />
              </Pressable>
              <Pressable disabled={!selectedTryOn} accessibilityRole="button" accessibilityLabel={t('ar.addThisProduct')} onPress={onAddCurrent} style={styles.addCurrent}>
                <Ionicons name={currentAdded ? 'checkmark' : 'bag-add-outline'} size={23} color="#FFFFFF" />
              </Pressable>
            </View>
            <View pointerEvents={zoneMenuOpen ? 'none' : 'auto'} aria-hidden={zoneMenuOpen} accessibilityElementsHidden={zoneMenuOpen} importantForAccessibility={zoneMenuOpen ? 'no-hide-descendants' : 'auto'} style={zoneMenuOpen ? { opacity: 0 } : undefined}>
            <OpenArcPalette key={JSON.stringify([zone, nearby.active, nearby.anchor?.product.id, nearby.anchor?.shade.id, nearby.direction, textureFilter, familyFilter, careChip])}
              items={displayedSwatches} selected={(careOpen ? selectedCare : selectedTryOn) ?? undefined} label={t('ar.arc.palette')} hint={t('ar.arc.swipe')}
              onSelect={({ product, shade }) => {
                if (careOpen && careSelection?.productId === product.id && careSelection.shadeId === shade.id) clearLipCare();
                else if (!careOpen && selections[zone]?.productId === product.id && selections[zone]?.shadeId === shade.id) clearZone(zone);
                else applyShade(product, shade);
                Haptics.selectionAsync().catch(() => {});
              }} />
            </View>
            <View style={[styles.hubRow, zoneMenuOpen && { marginTop: -zoneWheelRadius(windowWidth) }]}>
              {!zoneMenuOpen && nearby.active && nearby.canRebase ? <Pressable accessibilityRole="button" accessibilityLabel={t('ar.explore.rebase')} onPress={nearby.rebase} style={styles.rebase}>
                <Text style={styles.whiteText}>{t('ar.explore.rebase')}</Text>
              </Pressable> : null}
              <ArZoneWheel zones={AR_PAINT_ZONES} selected={zone} labels={Object.fromEntries(AR_PAINT_ZONES.map((z) => [z, t(`ar.zone.${z}` as TranslationKey)]))}
                hint={t('ar.arc.hold')} openHint={t('ar.arc.release')} openLabel={t('ar.arc.zones')} closeLabel={t('common.cancel')} onSelect={chooseZone} onOpenChange={setZoneMenuOpen} />
              {!zoneMenuOpen ? <Pressable accessibilityRole="button" accessibilityLabel={t('ar.arc.info')} onPress={() => setSheet('info')} style={styles.infoButton}>
                <Ionicons name="information-circle-outline" size={20} color="#FFFFFF" />
              </Pressable> : null}
            </View>
          </View>
        )}
      </SafeAreaView>
      {!isFullscreenAR && sheet ? (
        <ArSheet title={t(sheet === 'tools' ? 'ar.arc.tools' : sheet === 'product' ? 'ar.openProduct' : 'ar.arc.info')} closeLabel={t('common.cancel')} bottomInset={insets.bottom} onClose={() => setSheet(null)}>
          {sheet === 'tools' && mode === 'direct' ? detailPanel : (
            <ScrollView style={{ maxHeight: windowHeight * 0.55 }} contentContainerStyle={styles.sheetContent}>
              {sheet === 'product' ? productDetails : null}
              {sheet === 'info' && mode === 'chat' ? <Text style={styles.matchNote}>{t('ar.micUnavailable')}</Text> : null}
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
  notices: { gap: 4, zIndex: 2 },
  sampleNotice: { alignSelf: 'center', paddingHorizontal: 10, paddingVertical: 4, borderRadius: 12, color: '#FFFFFF', fontSize: 10, backgroundColor: 'rgba(30,22,27,0.6)' },
  arcDock: { position: 'absolute', bottom: 0, width: '100%' },
  sideControls: { position: 'absolute', width: '100%', paddingHorizontal: 16, height: 226, zIndex: 8 },
  leftTools: { position: 'absolute', left: 16, top: 58, gap: 6, zIndex: 4 },
  sideControl: { width: 44, minHeight: 52, alignItems: 'center', justifyContent: 'center', gap: 3 },
  sideLabel: { fontSize: 10, color: '#FFFFFF', fontWeight: '600', textShadowColor: 'rgba(0,0,0,0.75)', textShadowOffset: { width: 0, height: 1 }, textShadowRadius: 3 },
  sideIcon: { width: 32, height: 32, borderRadius: 16, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(30,22,27,0.5)' },
  selectedTool: { backgroundColor: theme.colors.rose, borderWidth: 1, borderColor: '#FFFFFF' },
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
  toolActions: { paddingHorizontal: 16, flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
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
  swatches: { gap: 10, paddingHorizontal: 16 },
  swatchItem: { width: 70, alignItems: 'center' },
  swatchRing: { width: 50, height: 50, borderRadius: 25, borderWidth: 2, borderColor: 'transparent', alignItems: 'center', justifyContent: 'center' },
  swatchRingActive: { borderColor: theme.colors.rose },
  swatch: { width: 40, height: 40, borderRadius: 20, borderWidth: 1, borderColor: 'rgba(0,0,0,0.08)' },
  swatchBrand: { fontSize: 10, color: theme.colors.inkFaint, marginTop: 4 },
  swatchName: { fontSize: 11, color: theme.colors.ink, fontWeight: '600' },
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
  chatComposer: { height: 88, flexShrink: 0, paddingTop: 6, paddingHorizontal: 18 },
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
