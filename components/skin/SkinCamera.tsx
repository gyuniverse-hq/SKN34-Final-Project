import { useMemo, useRef, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { WebView } from 'react-native-webview';
import { Button } from '@/components/ui/Button';
import { theme } from '@/constants/theme';
import { getSkinCameraView } from '@/lib/skinAnalysis';
import { skinWebCaptureScript, skinWebHtml } from '@/lib/skinWebHtml';
import { useI18n } from '@/lib/i18n';
import type { SkinCameraEvent, SkinWebEvent, SkinWebRun } from '@/types/skin';

function NativeCamera({ onCapture }: { onCapture: (event: SkinCameraEvent) => void }) {
  const [Camera] = useState(() => getSkinCameraView());
  return <Camera active style={StyleSheet.absoluteFill} onCaptureState={event => onCapture(event.nativeEvent)} />;
}

export function SkinCamera({ state, onCapture, webRun, onWebEvent, analyzing = false }: {
  state: SkinCameraEvent; onCapture: (event: SkinCameraEvent) => void;
  webRun?: SkinWebRun; onWebEvent: (event: SkinWebEvent) => void; analyzing?: boolean;
}) {
  const { t } = useI18n();
  const webView = useRef<WebView<unknown>>(null);
  const source = useMemo(() => webRun ? { html: skinWebHtml(webRun), baseUrl: 'https://localhost/' } : undefined, [webRun]);
  const canCaptureManually = webRun && !webRun.photoBase64 && !analyzing;
  const captureDisabled = ['loading', 'openingCamera', 'loadingGuide', 'capturing', 'cameraError'].includes(state.guidance);
  const failed = () => onWebEvent({ type: 'error', code: 'model' });
  return <>
    <View style={analyzing ? styles.hidden : styles.frame}>
      {source ? <WebView<unknown> ref={webView} source={source} originWhitelist={['*']} javaScriptEnabled
        allowsInlineMediaPlayback mediaPlaybackRequiresUserAction={false} mediaCapturePermissionGrantType="grant"
        mixedContentMode="always" allowFileAccess={false} scrollEnabled={false}
        onMessage={event => {
          try {
            if (event.nativeEvent.data.length > 65536) return failed();
            onWebEvent(JSON.parse(event.nativeEvent.data) as SkinWebEvent);
          } catch { failed(); }
        }} onError={failed} onContentProcessDidTerminate={failed} onRenderProcessGone={failed}
        containerStyle={styles.webView} style={styles.webView} renderError={() => <View style={styles.webView} />} /> : <NativeCamera onCapture={onCapture} />}
      {!analyzing && <View pointerEvents="none" style={StyleSheet.absoluteFill}>
        <View style={[styles.guide, state.guidance === 'hold' && styles.ready]}>
          <View style={styles.forehead}><Text style={styles.small}>{t('skin.foreheadLine')}</Text></View>
        </View>
        <View style={styles.caption}>
          <Text accessibilityLiveRegion="polite" style={styles.text}>{t(`skin.guidance.${state.guidance}`)}</Text>
          <View style={styles.track}><View style={[styles.fill, { width: `${Math.round(state.progress * 100)}%` }]} /></View>
        </View>
      </View>}
    </View>
    {!analyzing && <Text style={styles.instructions}>{t('skin.instructions')}</Text>}
    {canCaptureManually && <Button label={t('skin.capture')} icon="camera-outline" disabled={captureDisabled}
      onPress={() => webView.current?.injectJavaScript(skinWebCaptureScript)} />}
  </>;
}

const styles = StyleSheet.create({
  frame: { flex: 1, minHeight: 240, backgroundColor: '#111', overflow: 'hidden', borderRadius: 24 },
  webView: { flex: 1, backgroundColor: '#111' },
  hidden: { position: 'absolute', width: 1, height: 1, opacity: 0, overflow: 'hidden' },
  // Native camera gate uses these same normalized guide coordinates.
  guide: { position: 'absolute', left: '15%', top: '12%', width: '70%', height: '68%', borderRadius: 240, borderWidth: 3, borderColor: '#fff' },
  ready: { borderColor: '#73e6ab' },
  forehead: { top: '18%', marginHorizontal: '17%', borderTopWidth: 1, borderStyle: 'dashed', borderColor: '#fff' },
  small: { color: '#fff', textAlign: 'center', fontSize: 12, marginTop: 4, textShadowColor: '#000', textShadowRadius: 3 },
  caption: { position: 'absolute', bottom: 24, left: 20, right: 20, backgroundColor: '#000a', borderRadius: 16, padding: 14, gap: 10 },
  text: { color: '#fff', textAlign: 'center', fontSize: 16 },
  instructions: { fontSize: 14, color: theme.colors.inkMuted, textAlign: 'center' },
  track: { height: 5, backgroundColor: '#ffffff55', borderRadius: 4, overflow: 'hidden' },
  fill: { height: 5, backgroundColor: '#73e6ab' },
});
