import { Stack, useRouter } from 'expo-router';
import { useQueryClient } from '@tanstack/react-query';
import { skinAccessKey, useSkinAccess } from '@/hooks/useSkinAccess';
import { ApiError } from '@/lib/api';
import { registerSkinReport } from '@/lib/skinRegistration';
import type { SkinProfileV4 } from '@/types/skin';
import { useCameraPermissions } from 'expo-camera';
import * as ImagePicker from 'expo-image-picker';
import Ionicons from '@expo/vector-icons/Ionicons';
import { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, BackHandler, FlatList, Linking, Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Button } from '@/components/ui/Button';
import { SkinCamera } from '@/components/skin/SkinCamera';
import { SkinSurvey } from '@/components/skin/SkinSurvey';
import { theme } from '@/constants/theme';
import { useSkinAnalysis } from '@/hooks/useSkinAnalysis';
import { useI18n } from '@/lib/i18n';
import { skinAnalysisSupported, skinAnalysisUsesWebView } from '@/lib/skinAnalysis';
import type { ComparisonGender } from '@/types/recommendationComparison';

export default function SkinAnalysisScreen() {
  const access = useSkinAccess();
  return <AnalysisSession key={access.owner} access={access} />;
}

function AnalysisSession({ access }: { access: ReturnType<typeof useSkinAccess> }) {
  const { t } = useI18n();
  const router = useRouter();
  const usedFreeAnalysis = useRef(false);
  const cache = useQueryClient();
  const register = async (profile: SkinProfileV4) => {
    try { usedFreeAnalysis.current = await registerSkinReport(profile, access.owner) === 'free'; }
    catch (error) {
      if (error instanceof ApiError && error.code === 'skin_access_required') {
        void access.retry();
        router.replace('/membership');
      }
      throw error;
    }
    void cache.invalidateQueries({ queryKey: skinAccessKey(access.owner) });
  };
  const [permission, requestPermission] = useCameraPermissions();
  const [birthYear, setBirthYear] = useState<number>();
  const [yearPickerOpen, setYearPickerOpen] = useState(false);
  const [gender, setGender] = useState<ComparisonGender>();
  const year = new Date().getFullYear();
  const years = Array.from({ length: Math.max(0, year - 1900 + 1) }, (_, index) => year - index);
  const flow = useSkinAnalysis({ ...(birthYear !== undefined ? { birthYear } : {}), ...(gender ? { gender } : {}) }, register);
  const [photoError, setPhotoError] = useState(false);
  const { phase, cancel } = flow;
  useEffect(() => {
    if (phase === 'done') router.replace(usedFreeAnalysis.current
      ? { pathname: '/skin-recommendations', params: { freeTrial: '1' } } : '/skin-recommendations');
  }, [phase, router]);
  const leave = () => { flow.cancel(); if (router.canGoBack()) router.back(); else router.replace('/(tabs)'); };
  useEffect(() => {
    const subscription = BackHandler.addEventListener('hardwareBackPress', () => {
      if (phase !== 'saving') { cancel(); if (router.canGoBack()) router.back(); else router.replace('/(tabs)'); }
      return true;
    });
    return () => subscription.remove();
  }, [phase, cancel, router]);

  async function begin() {
    const allowed = permission?.granted || (await requestPermission()).granted;
    if (allowed) await flow.start();
  }
  async function choosePhoto() {
    setPhotoError(false);
    try {
      const selected = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ['images'], base64: true, quality: 0.8 });
      if (selected.canceled) return;
      const photo = selected.assets[0]?.base64;
      if (!photo || photo.length > 16 * 1024 * 1024) { setPhotoError(true); return; }
      await flow.start(photo);
    } catch { setPhotoError(true); }
  }
  return <SafeAreaView edges={['bottom']} style={styles.screen}>
    <Stack.Screen options={{ title: t('skin.title'), headerBackVisible: false, gestureEnabled: false }} />
    {(flow.phase === 'camera' || (flow.phase === 'analysis' && flow.webRun)) && <SkinCamera
      state={flow.camera} onCapture={flow.onCapture} webRun={flow.webRun} onWebEvent={flow.onWebEvent} analyzing={flow.phase === 'analysis'} />}
    {!skinAnalysisSupported ? <View style={styles.center}>
      <Text style={styles.body}>{t('skin.unsupported')}</Text>
    </View> : flow.phase === 'ready' && !access.ready ? <View style={styles.center}>
      {access.error ? <Button label={t('skin.retry')} onPress={() => { void access.retry(); }} />
        : <ActivityIndicator color={theme.colors.rose} />}
    </View> : flow.phase === 'ready' && access.trialUsed && !access.subscribed ? <View style={styles.center}>
      <Text style={styles.body}>{t('skinAccess.used')}</Text>
      <Button label={t('skinAccess.viewMembership')} onPress={() => router.replace('/membership')} />
    </View> : flow.phase === 'ready' ? <ScrollView contentContainerStyle={styles.ready} keyboardShouldPersistTaps="handled">
      <Text style={styles.title}>{t('skin.title')}</Text>
      <Text style={styles.body}>{t('skin.instructions')}</Text>
      <Text style={styles.body}>{t('skin.localNotice')}</Text>
      <View style={styles.fields}>
        <Text style={styles.label}>{t('skin.birthYearOptional')}</Text>
        <Pressable accessibilityRole="button" accessibilityLabel={t('skin.birthYearOptional')}
          accessibilityValue={{ text: birthYear === undefined ? t('skin.birthYearPlaceholder') : String(birthYear) }}
          onPress={() => setYearPickerOpen(true)} style={styles.input}>
          <Text style={birthYear === undefined ? styles.placeholder : styles.label}>
            {birthYear ?? t('skin.birthYearPlaceholder')}
          </Text>
          <Ionicons name="chevron-down" size={20} color={theme.colors.inkMuted} />
        </Pressable>
        <Text style={styles.label}>{t('skin.genderOptional')}</Text>
        <View style={styles.choices}>
          {(['남성', '여성'] as const).map(value => <Pressable key={value} accessibilityRole="radio"
            accessibilityState={{ checked: gender === value }} onPress={() => setGender(previous => previous === value ? undefined : value)}
            style={[styles.choice, gender === value && styles.selected]}>
            <Text style={styles.label}>{t(value === '남성' ? 'comparison.male' : 'comparison.female')}</Text>
          </Pressable>)}
        </View>
        <Text style={styles.help}>{t('skin.demographicsStorage')}</Text>
      </View>
      {skinAnalysisUsesWebView && <Text style={styles.help}>{t('skin.expoHelp')}</Text>}
      {photoError && <Text accessibilityRole="alert" style={styles.body}>{t('skin.photoError')}</Text>}
      {permission && !permission.granted && !permission.canAskAgain ? <>
        <Text style={styles.body}>{t('skin.permissionDenied')}</Text>
        <Button label={t('skin.openSettings')} onPress={() => { void Linking.openSettings(); }} />
      </> : <Button label={t('skin.start')} onPress={() => { void begin(); }} />}
      {skinAnalysisUsesWebView && <Button label={t('skin.choosePhoto')} variant="secondary" onPress={() => { void choosePhoto(); }} />}
    </ScrollView> : flow.phase === 'camera' ? <>
      <Text style={styles.help}>{t('skin.instructions')}</Text>
    </> : flow.phase === 'analysis' ? <View style={styles.center}>
      <ActivityIndicator size="large" color={theme.colors.rose} />
      <Text style={styles.title}>{t('skin.analyzing')}</Text>
      <Text accessibilityLiveRegion="polite" style={styles.body}>{t(`skin.indicator.${flow.indicator}`)}</Text>
    </View> : flow.phase === 'survey' || flow.phase === 'saving' ? <SkinSurvey answers={flow.answers} onChange={flow.setAnswers}
      onFinish={() => { void flow.finish(); }} complete={flow.complete} saving={flow.phase === 'saving'} error={flow.error === 'storage'} />
      : flow.phase === 'done' ? <View style={styles.center}><ActivityIndicator color={theme.colors.rose} /></View> : <View style={styles.center}>
        <Text accessibilityRole="alert" style={styles.body}>{t(flow.error === 'permission' ? 'skin.permissionDenied' : flow.error === 'model' ? 'skin.modelFailed' : flow.error === 'camera' ? 'skin.guidance.cameraError' : flow.error === 'guide' ? 'skin.guideFailed' : 'skin.analysisFailed')}</Text>
        {flow.error === 'permission' && <Button label={t('skin.openSettings')} onPress={() => { void Linking.openSettings(); }} />}
        {photoError && <Text accessibilityRole="alert" style={styles.body}>{t('skin.photoError')}</Text>}
        <Button label={t('skin.retry')} onPress={() => { void begin(); }} />
        {skinAnalysisUsesWebView && <Button label={t('skin.choosePhoto')} variant="secondary" onPress={() => { void choosePhoto(); }} />}
      </View>}
    {flow.phase !== 'done' && <Button variant="ghost" label={t('common.cancel')} disabled={flow.phase === 'saving'} onPress={leave} />}
    <Modal visible={yearPickerOpen} transparent animationType="slide" onRequestClose={() => setYearPickerOpen(false)}>
      <View style={styles.modalOverlay}>
        <Pressable style={StyleSheet.absoluteFill} accessibilityRole="button" accessibilityLabel={t('common.cancel')} onPress={() => setYearPickerOpen(false)} />
        <View style={styles.yearSheet}>
          <Text style={styles.yearTitle}>{t('skin.birthYearOptional')}</Text>
          <Pressable accessibilityRole="button" onPress={() => { setBirthYear(undefined); setYearPickerOpen(false); }} style={styles.yearRow}>
            <Text style={styles.label}>{t('skin.birthYearNone')}</Text>
          </Pressable>
          <FlatList data={years} keyExtractor={item => String(item)} renderItem={({ item }) => (
            <Pressable accessibilityRole="radio" accessibilityState={{ checked: birthYear === item }}
              onPress={() => { setBirthYear(item); setYearPickerOpen(false); }} style={styles.yearRow}>
              <Text style={styles.label}>{item}</Text>
              {birthYear === item && <Ionicons name="checkmark" size={20} color={theme.colors.rose} />}
            </Pressable>
          )} />
          <Button label={t('common.cancel')} variant="ghost" onPress={() => setYearPickerOpen(false)} />
        </View>
      </View>
    </Modal>
  </SafeAreaView>;
}
const styles = StyleSheet.create({
  screen: { flex: 1, padding: 20, gap: 16, backgroundColor: theme.colors.surface },
  center: { flex: 1, justifyContent: 'center', gap: 24 },
  ready: { flexGrow: 1, justifyContent: 'center', gap: 18, paddingVertical: 12 },
  fields: { gap: 8 },
  label: { fontSize: 15, fontWeight: '600', color: theme.colors.ink },
  input: { minHeight: 48, borderWidth: 1, borderColor: theme.colors.border, borderRadius: theme.radius.md, paddingHorizontal: 12, backgroundColor: theme.colors.card, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  placeholder: { fontSize: 15, color: theme.colors.inkMuted },
  choices: { flexDirection: 'row', gap: 10 },
  choice: { flex: 1, minHeight: 48, borderWidth: 1, borderColor: theme.colors.border, borderRadius: theme.radius.md, alignItems: 'center', justifyContent: 'center', backgroundColor: theme.colors.card },
  selected: { borderColor: theme.colors.rose, backgroundColor: theme.colors.roseSoft },
  modalOverlay: { flex: 1, backgroundColor: 'rgba(0,0,0,0.45)', justifyContent: 'flex-end' },
  yearSheet: { height: '60%', backgroundColor: theme.colors.surface, borderTopLeftRadius: 20, borderTopRightRadius: 20, paddingHorizontal: 20, paddingTop: 20, paddingBottom: 16 },
  yearTitle: { fontSize: 18, fontWeight: '700', color: theme.colors.ink, marginBottom: 8 },
  yearRow: { minHeight: 48, flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: 8 },
  title: { fontSize: 24, fontWeight: '700', textAlign: 'center', color: theme.colors.ink },
  body: { fontSize: 16, lineHeight: 25, textAlign: 'center', color: theme.colors.inkMuted },
  help: { fontSize: 14, color: theme.colors.inkMuted, textAlign: 'center' },
});
