import { useCallback, useEffect, useRef } from 'react';
import { StyleSheet } from 'react-native';
import { WebView, type WebViewMessageEvent } from 'react-native-webview';
import type { MakeupState } from '@/types';
import { FACE_TRACKER_HTML, type ArStatus } from './faceTrackerHtml';

export interface ArFaceViewProps {
  makeup: MakeupState;
  compare: boolean;
  onStatus: (status: ArStatus) => void;
}

export function ArFaceView({ makeup, compare, onStatus }: ArFaceViewProps) {
  const ref = useRef<WebView>(null);
  const latest = useRef({ makeup, compare });
  useEffect(() => {
    latest.current = { makeup, compare };
  });

  const send = useCallback((message: object) => {
    const payload = JSON.stringify(JSON.stringify(message));
    ref.current?.injectJavaScript(`window.__kb && window.__kb.receive(${payload}); true;`);
  }, []);

  useEffect(() => send({ type: 'makeup', makeup }), [makeup, send]);
  useEffect(() => send({ type: 'compare', value: compare }), [compare, send]);

  const onMessage = (event: WebViewMessageEvent) => {
    let message: { type?: string; status?: ArStatus; detail?: string };
    try {
      message = JSON.parse(event.nativeEvent.data);
    } catch {
      return;
    }
    if (message.type === 'hello') {
      send({ type: 'makeup', makeup: latest.current.makeup });
      send({ type: 'compare', value: latest.current.compare });
    } else if (message.type === 'status' && message.status) {
      if (__DEV__ && message.detail) console.warn('[ar]', message.status, message.detail);
      onStatus(message.status);
    }
  };

  return (
    <WebView
      ref={ref}
      source={{ html: FACE_TRACKER_HTML, baseUrl: 'https://localhost/' }}
      originWhitelist={['*']}
      onMessage={onMessage}
      javaScriptEnabled
      allowsInlineMediaPlayback
      mediaPlaybackRequiresUserAction={false}
      mediaCapturePermissionGrantType="grant"
      scrollEnabled={false}
      bounces={false}
      overScrollMode="never"
      onError={() => onStatus('unavailable')}
      webviewDebuggingEnabled={__DEV__}
      style={styles.webview}
      containerStyle={styles.webview}
    />
  );
}

const styles = StyleSheet.create({
  webview: { flex: 1, backgroundColor: '#000' },
});
