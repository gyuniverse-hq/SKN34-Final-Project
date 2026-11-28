import { useEffect, useRef } from 'react';
import { WebView } from 'react-native-webview';
import { VOICE_SESSION_HTML } from './voiceSessionHtml';

type BridgeMessage = { type: string; sdp?: string; args?: Record<string, unknown>; screenMs?: number; speechMs?: number };
export function VoiceSessionView({ onOffer, onTool, onPhase, onFailure, onEnd }: {
  onOffer: (sdp: string) => Promise<string>;
  onTool: (args: Record<string, unknown>) => Promise<string | undefined>;
  onPhase: (phase: 'recording' | 'thinking' | 'speaking') => void;
  onFailure: () => void;
  onEnd: () => void;
}) {
  const view = useRef<WebView<Record<string, unknown>>>(null);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const handle = async (raw: string) => {
    try {
      const message: BridgeMessage = JSON.parse(raw);
      if (message.type === 'loaded') view.current?.injectJavaScript('window.startVoice(); true;');
      if (message.type === 'offer' && message.sdp) {
        const answer = await onOffer(message.sdp);
        if (alive.current) view.current?.injectJavaScript(`window.setAnswer(${JSON.stringify(answer)}); true;`);
      }
      if (message.type === 'ready') onPhase('recording');
      if (message.type === 'speaking') onPhase('speaking');
      if (message.type === 'tool' && message.args) {
        onPhase('thinking');
        const result = await onTool(message.args);
        if (alive.current) view.current?.injectJavaScript(`window.toolResult(${JSON.stringify(JSON.parse(result ?? '{"status":"REJECTED"}'))}); true;`);
      }
      if (message.type === 'metrics') console.info('[ar-voice-timing]', { screenMs: message.screenMs, speechMs: message.speechMs });
      if (message.type === 'failed') onFailure();
      if (message.type === 'ended') onEnd();
    } catch { if (alive.current) onFailure(); }
  };
  return <WebView<Record<string, unknown>> ref={view} source={{ html: VOICE_SESSION_HTML, baseUrl: 'https://localhost/' }}
    originWhitelist={['about:blank', 'https://localhost']} onShouldStartLoadWithRequest={req => req.url === 'about:blank' || req.url === 'https://localhost/'}
    onMessage={event => { void handle(event.nativeEvent.data); }} onError={onFailure}
    mediaCapturePermissionGrantType="grant" allowsInlineMediaPlayback mediaPlaybackRequiresUserAction={false}
    style={{ width: 1, height: 1 }} containerStyle={{ position: 'absolute', width: 1, height: 1 }} />;
}
