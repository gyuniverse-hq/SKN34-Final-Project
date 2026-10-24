import { Stack, useRouter } from 'expo-router';
import { useCameraPermissions } from 'expo-camera';
import { useEffect } from 'react';
import { ActivityIndicator, BackHandler, Linking, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Button } from '@/components/ui/Button';
import { SkinCamera } from '@/components/skin/SkinCamera';
import { SkinSurvey } from '@/components/skin/SkinSurvey';
import { useAuth } from '@/lib/auth';
import { theme } from '@/constants/theme';
import { useSkinAnalysis } from '@/hooks/useSkinAnalysis';
import { useI18n } from '@/lib/i18n';
import { skinAnalysisSupported, skinAnalysisUsesWebView, skinAnalysisServerMode } from '@/lib/skinAnalysis';

export default function SkinAnalysisScreen() {
  const { t } = useI18n();
  const router = useRouter();
  const [permission, requestPermission] = useCameraPermissions();
  const flow = useSkinAnalysis();
  const { user, ready } = useAuth();
  const { phase, cancel } = flow;
  const leave = () => { flow.cancel(); router.replace('/(tabs)/my'); };
  useEffect(() => {
    const subscription = BackHandler.addEventListener('hardwareBackPress', () => {
      if (phase !== 'saving') { cancel(); router.replace('/(tabs)/my'); }
      return true;
    });
    return () => subscription.remove();
  }, [phase, cancel, router]);

  async function begin() {
    if (skinAnalysisServerMode && !ready) return;
    if (skinAnalysisServerMode && !user) { router.push('/login'); return; }
    const allowed = permission?.granted || (await requestPermission()).granted;
    if (allowed) await flow.start();
  }
  return <SafeAreaView edges={['bottom']} style={styles.screen}>
    <Stack.Screen options={{ title: t('skin.title'), headerBackVisible: false, gestureEnabled: false }} />
    {(flow.phase === 'camera' || (flow.phase === 'analysis' && flow.webRun)) && <SkinCamera
      state={flow.camera} onCapture={flow.onCapture} webRun={flow.webRun} onWebEvent={flow.onWebEvent} analyzing={flow.phase === 'analysis'} />}
    {!skinAnalysisSupported ? <View style={styles.center}>
      <Text style={styles.body}>{t('skin.unsupported')}</Text>
    </View> : flow.phase === 'ready' ? <View style={styles.center}>
      <Text style={styles.title}>{t('skin.title')}</Text>
      <Text style={styles.body}>{t('skin.instructions')}</Text>
      <Text style={styles.body}>{t(skinAnalysisServerMode ? 'skin.serverNotice' : 'skin.localNotice')}</Text>
      {skinAnalysisUsesWebView && <Text style={styles.help}>{t(skinAnalysisServerMode ? 'skin.serverHelp' : 'skin.expoHelp')}</Text>}
      {permission && !permission.granted && !permission.canAskAgain ? <>
        <Text style={styles.body}>{t('skin.permissionDenied')}</Text>
        <Button label={t('skin.openSettings')} onPress={() => { void Linking.openSettings(); }} />
      </> : <Button label={t('skin.start')} onPress={() => { void begin(); }} />}
    </View> : flow.phase === 'camera' ? <>
      <Text style={styles.help}>{t('skin.instructions')}</Text>
    </> : flow.phase === 'analysis' ? <View style={styles.center}>
      <ActivityIndicator size="large" color={theme.colors.rose} />
      <Text style={styles.title}>{t('skin.analyzing')}</Text>
      <Text accessibilityLiveRegion="polite" style={styles.body}>{t(skinAnalysisServerMode ? 'skin.serverProcessing' : `skin.indicator.${flow.indicator}`)}</Text>
    </View> : flow.phase === 'survey' || flow.phase === 'saving' ? <SkinSurvey answers={flow.answers} onChange={flow.setAnswers}
      onFinish={() => { void flow.finish(); }} complete={flow.complete} saving={flow.phase === 'saving'} error={flow.error === 'storage'} />
      : flow.phase === 'done' ? <View style={styles.center}>
        <Text accessibilityRole="header" style={styles.title}>{t('skin.completed')}</Text>
        <Button label={t('skin.confirm')} onPress={leave} />
      </View> : <View style={styles.center}>
        <Text accessibilityRole="alert" style={styles.body}>{t(flow.error === 'auth' ? 'skin.signInRequired' : flow.error === 'network' ? 'skin.serverUnavailable' : flow.error === 'busy' ? 'skin.serverBusy' : flow.error === 'permission' ? 'skin.permissionDenied' : flow.error === 'model' ? 'skin.modelFailed' : 'skin.analysisFailed')}</Text>
        {flow.error === 'permission' && <Button label={t('skin.openSettings')} onPress={() => { void Linking.openSettings(); }} />}
        <Button label={t(flow.error === 'auth' ? 'my.login' : 'skin.retry')} onPress={() => { if (flow.error === 'auth') router.push('/login'); else void begin(); }} />
      </View>}
    {flow.phase !== 'done' && <Button variant="ghost" label={t('common.cancel')} disabled={flow.phase === 'saving'} onPress={leave} />}
  </SafeAreaView>;
}
const styles = StyleSheet.create({
  screen: { flex: 1, padding: 20, gap: 16, backgroundColor: theme.colors.surface },
  center: { flex: 1, justifyContent: 'center', gap: 24 },
  title: { fontSize: 24, fontWeight: '700', textAlign: 'center', color: theme.colors.ink },
  body: { fontSize: 16, lineHeight: 25, textAlign: 'center', color: theme.colors.inkMuted },
  help: { fontSize: 14, color: theme.colors.inkMuted, textAlign: 'center' },
});
