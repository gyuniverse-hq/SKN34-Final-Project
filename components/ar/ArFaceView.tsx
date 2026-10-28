import { useCallback, useEffect, useRef } from 'react';
import { StyleSheet } from 'react-native';
import { WebView, type WebViewMessageEvent } from 'react-native-webview';
import type { GuideMessage } from '@/lib/drawGuide';
import type { MakeupState } from '@/types';
import { FACE_TRACKER_HTML, type ArStatus } from './faceTrackerHtml';

export interface ArFaceViewProps {
  makeup: MakeupState;
  compare: boolean;
  /** Drawing guide to show on the live face, or null/undefined for none. */
  guide?: GuideMessage | null;
  onStatus: (status: ArStatus) => void;
}

export function ArFaceView({ makeup, compare, guide = null, onStatus }: ArFaceViewProps) {
  // react-native-webview 14 types default the class generic to `undefined`, which makes every prop
  // `never`; an explicit `object` keeps the props typed.
  const ref = useRef<WebView<object>>(null);
  const latest = useRef({ makeup, compare, guide });
  useEffect(() => {
    latest.current = { makeup, compare, guide };
  });

  const send = useCallback((message: object) => {
    const payload = JSON.stringify(JSON.stringify(message));
    ref.current?.injectJavaScript(`window.__kb && window.__kb.receive(${payload}); true;`);
  }, []);

  useEffect(() => send({ type: 'makeup', makeup }), [makeup, send]);
  useEffect(() => send({ type: 'compare', value: compare }), [compare, send]);
  useEffect(() => send({ type: 'guide', guide }), [guide, send]);

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
      send({ type: 'guide', guide: latest.current.guide });
    } else if (message.type === 'status' && message.status) {
      if (__DEV__ && message.detail) console.warn('[ar]', message.status, message.detail);
      onStatus(message.status);
    }
  };

  return (
    <WebView<object>
      ref={ref}
      key={FACE_TRACKER_HTML.length}
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
