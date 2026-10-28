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
  // react-native-webview의 타입이 제네릭 기본값을 `never`로 잡는 경우가 있어,
  // 메시지/소스에 대해 넉넉한 타입을 명시해 props 타입 추론을 정상화합니다.
  const ref = useRef<WebView<any>>(null);
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
    <WebView<any>
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
