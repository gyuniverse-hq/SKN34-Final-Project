import Ionicons from '@expo/vector-icons/Ionicons';
import { useCameraPermissions } from 'expo-camera';
import * as Haptics from 'expo-haptics';
import { useFocusEffect, useRouter } from 'expo-router';
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
import { useI18n, type TranslationKey } from '@/lib/i18n';
import { useProducts } from '@/lib/queries';
import { useCartStore } from '@/store/cartStore';
import { useMakeupStore } from '@/store/makeupStore';
import { useSettingsStore } from '@/store/settingsStore';
import type { MakeupZone } from '@/types';

type Mode = 'direct' | 'chat';

const ZONES: MakeupZone[] = ['lip', 'blush', 'eyeshadow'];
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

export default function ArTryOnScreen() {
  const router = useRouter();
  const { t } = useI18n();
  const cameraConsent = useSettingsStore((s) => s.cameraConsent);
  const setCameraConsent = useSettingsStore((s) => s.setCameraConsent);
  const [permission, requestPermission] = useCameraPermissions();
  const cameraActive = useCameraActive();
  const [status, setStatus] = useState<ArStatus>('loading');
  const [compare, setCompare] = useState(false);
  const [zone, setZone] = useState<MakeupZone>('lip');
  const [added, setAdded] = useState(false);
  const [mode, setMode] = useState<Mode>('direct');
  const [draft, setDraft] = useState('');

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
    if (makeup.lip || makeup.blush || makeup.eyeshadow) return;
    const firstLip = tryOnProducts.find((p) => p.makeupZone === 'lip');
    if (firstLip?.shades[0]) applyShade(firstLip, firstLip.shades[0]);
  }, [tryOnProducts, makeup, applyShade]);

  useFocusEffect(
    useCallback(() => {
      setStatus('loading');
    }, [])
  );

  useEffect(() => {
    if (!added) return;
    const timer = setTimeout(() => setAdded(false), 1800);
    return () => clearTimeout(timer);
  }, [added]);

  const isWeb = Platform.OS === 'web';
  const permissionGranted = isWeb || permission?.granted;
  const permissionBlocked = !isWeb && permission && !permission.granted && !permission.canAskAgain;

  const onAllow = async () => {
    setCameraConsent(true);
    if (!isWeb && !permission?.granted) await requestPermission();
  };

  const selectionItems = Object.values(selections).filter(Boolean);
  const onAddSelection = () => {
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

  let stage: ReactNode;
  if (!cameraConsent || (!permissionGranted && !permissionBlocked)) {
    stage = (
      <View style={styles.consent}>
        <Ionicons name="scan-circle-outline" size={52} color={theme.colors.rose} />
        <Text style={styles.consentTitle}>{t('ar.consentTitle')}</Text>
        {(['ar.consentPoint1', 'ar.consentPoint2', 'ar.consentPoint3'] as const).map((key) => (
          <View key={key} style={styles.point}>
            <Ionicons name="shield-checkmark-outline" size={18} color={theme.colors.success} />
            <Text style={styles.pointText}>{t(key)}</Text>
          </View>
        ))}
        <Button label={t('ar.allowCamera')} icon="camera-outline" onPress={onAllow} style={styles.consentBtn} />
      </View>
    );
  } else if (permissionBlocked || status === 'denied') {
    stage = (
      <View style={styles.consent}>
        <Ionicons name="videocam-off-outline" size={44} color={theme.colors.inkFaint} />
        <Text style={styles.pointText}>{t('ar.cameraDenied')}</Text>
        {!isWeb ? (
          <Button label={t('ar.openSettings')} variant="secondary" onPress={() => Linking.openSettings()} style={styles.consentBtn} />
        ) : null}
      </View>
    );
  } else if (status === 'unavailable') {
    stage = <SwatchFallback message={t('ar.unavailable')} />;
  } else if (cameraActive) {
    stage = (
      <View style={styles.camera}>
        <ArFaceView makeup={makeup} compare={compare} onStatus={setStatus} />
        {status === 'loading' ? (
          <View style={styles.overlay} pointerEvents="none">
            <ActivityIndicator color={theme.colors.white} />
            <Text style={styles.overlayText}>{t('ar.loading')}</Text>
          </View>
        ) : null}
        {status === 'no-face' ? (
          <View style={styles.hintPill} pointerEvents="none">
            <Text style={styles.hintText}>{t('ar.noFace')}</Text>
          </View>
        ) : null}
        <View style={styles.liveBadge} pointerEvents="none">
          <View style={styles.liveDot} />
          <Text style={styles.liveText}>{t('ar.live')}</Text>
        </View>
        <Pressable
          onPressIn={() => setCompare(true)}
          onPressOut={() => setCompare(false)}
          accessibilityRole="button"
          accessibilityLabel={t('ar.compare')}
          style={styles.compareBtn}>
          <Ionicons name="contrast-outline" size={18} color={theme.colors.white} />
          <Text style={styles.compareText}>{t('ar.compare')}</Text>
        </Pressable>
      </View>
    );
  } else {
    stage = <View style={styles.camera} />;
  }

  return (
    <SafeAreaView style={styles.screen} edges={['top']}>
      <View style={styles.stage}>{stage}</View>

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
              {ZONES.map((z) => (
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

            {zoneSwatches.length === 0 ? <Text style={styles.noProducts}>{t('ar.noProducts')}</Text> : null}
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

            <View style={styles.actions}>
              <Button
                label={added ? t('ar.addedSelection') : t('ar.addSelection')}
                icon={added ? 'checkmark' : 'cart-outline'}
                disabled={selectionItems.length === 0}
                onPress={onAddSelection}
                style={{ flex: 1 }}
              />
              <Button
                label={t('ar.browseLooks')}
                variant="secondary"
                icon="sparkles-outline"
                onPress={() => router.push('/celeb')}
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
  camera: { flex: 1, backgroundColor: theme.colors.black },
  consent: { flex: 1, padding: 28, alignItems: 'center', justifyContent: 'center', gap: 12, backgroundColor: theme.colors.surface },
  consentTitle: { fontSize: theme.font.h2, fontWeight: '800', color: theme.colors.ink, textAlign: 'center', marginBottom: 6 },
  point: { flexDirection: 'row', gap: 10, alignItems: 'flex-start', alignSelf: 'stretch' },
  pointText: { flex: 1, fontSize: theme.font.body, color: theme.colors.inkMuted, lineHeight: 21, textAlign: 'left' },
  consentBtn: { alignSelf: 'stretch', marginTop: 10 },
  overlay: { position: 'absolute', top: 0, right: 0, bottom: 0, left: 0, alignItems: 'center', justifyContent: 'center', gap: 10, backgroundColor: 'rgba(0,0,0,0.35)' },
  overlayText: { color: theme.colors.white, fontSize: theme.font.small, fontWeight: '600' },
  hintPill: { position: 'absolute', bottom: 64, alignSelf: 'center', backgroundColor: theme.colors.overlay, paddingHorizontal: 14, paddingVertical: 8, borderRadius: theme.radius.pill },
  hintText: { color: theme.colors.white, fontSize: theme.font.small, fontWeight: '600' },
  liveBadge: { position: 'absolute', top: 12, left: 12, flexDirection: 'row', alignItems: 'center', gap: 6, backgroundColor: theme.colors.overlay, paddingHorizontal: 10, paddingVertical: 5, borderRadius: theme.radius.pill },
  liveDot: { width: 7, height: 7, borderRadius: 4, backgroundColor: '#4ADE80' },
  liveText: { color: theme.colors.white, fontSize: 11, fontWeight: '600' },
  compareBtn: { position: 'absolute', bottom: 14, alignSelf: 'center', flexDirection: 'row', alignItems: 'center', gap: 6, backgroundColor: theme.colors.overlay, paddingHorizontal: 14, paddingVertical: 9, borderRadius: theme.radius.pill },
  compareText: { color: theme.colors.white, fontSize: theme.font.small, fontWeight: '600' },
  panel: { backgroundColor: theme.colors.surface, borderTopLeftRadius: theme.radius.lg, borderTopRightRadius: theme.radius.lg, marginTop: 10, paddingTop: 14, paddingBottom: 12, gap: 10 },
  lookBanner: { marginHorizontal: 16, fontSize: 12, fontWeight: '700', color: theme.colors.rose },
  zoneRow: { flexDirection: 'row', marginHorizontal: 16, backgroundColor: theme.colors.surfaceAlt, borderRadius: theme.radius.md, padding: 3 },
  zoneTab: { flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, paddingVertical: 8, borderRadius: 10 },
  zoneTabActive: { backgroundColor: theme.colors.card, ...theme.shadow },
  zoneDot: { width: 10, height: 10, borderRadius: 5 },
  zoneText: { fontSize: theme.font.small, fontWeight: '600', color: theme.colors.inkMuted },
  zoneTextActive: { color: theme.colors.ink },
  swatches: { gap: 10, paddingHorizontal: 16 },
  swatchItem: { width: 70, alignItems: 'center' },
  swatchRing: { width: 50, height: 50, borderRadius: 25, borderWidth: 2, borderColor: 'transparent', alignItems: 'center', justifyContent: 'center' },
  swatchRingActive: { borderColor: theme.colors.ink },
  swatch: { width: 40, height: 40, borderRadius: 20, borderWidth: 1, borderColor: 'rgba(0,0,0,0.08)' },
  swatchBrand: { fontSize: 10, color: theme.colors.inkFaint, marginTop: 4 },
  swatchName: { fontSize: 11, color: theme.colors.ink, fontWeight: '600' },
  levels: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 16, flexWrap: 'wrap' },
  levelsLabel: { fontSize: 12, fontWeight: '700', color: theme.colors.inkMuted, marginRight: 4 },
  actions: { flexDirection: 'row', gap: 10, paddingHorizontal: 16 },
  noProducts: { marginHorizontal: 16, fontSize: theme.font.small, color: theme.colors.inkMuted },
  modeRow: { flexDirection: 'row', gap: 8, marginHorizontal: 16 },
  modeTab: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 14, paddingVertical: 7, borderRadius: theme.radius.pill, backgroundColor: theme.colors.surfaceAlt },
  modeTabActive: { backgroundColor: theme.colors.ink },
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
