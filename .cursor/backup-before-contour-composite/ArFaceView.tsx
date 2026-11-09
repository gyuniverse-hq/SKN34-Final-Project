import { useCallback, useEffect, useRef } from 'react';
import { StyleSheet } from 'react-native';
import { WebView, type WebViewMessageEvent } from 'react-native-webview';
import type { GuideMessage } from '@/lib/drawGuide';
import { parseRecorderMessage, type RecorderMessage } from '@/lib/arRecording';
import { parseFaceFit, parseFaceFitStatus, parseFaceShape, type FaceFitHint, type FaceFitStatus, type FaceShapeReading } from '@/lib/faceFit';
import { parseSkinTone, type SkinTone } from '@/lib/foundationMatch';
import type { ArRenderCommand, ArRenderResult, MakeupState } from '@/types';
import { FACE_TRACKER_HTML, type ArStatus } from './faceTrackerHtml';

export type LightHint = 'low' | 'blown';

export interface ArFaceViewProps {
  makeup: MakeupState;
  compare: boolean;
  /** Drawing guide to show on the live face, or null/undefined for none. */
  guide?: GuideMessage | null;
  /** Full-screen AR: pick cover vs contain+blur fill from the video vs view aspect. */
  fillPreview?: boolean;
  onStatus: (status: ArStatus) => void;
  onLightHint?: (hint: LightHint | null) => void;
  /** Measured skin color for the foundation shade suggestion (numbers only). */
  onSkinTone?: (tone: SkinTone) => void;
  /** Placement hints from this face's measured ratios (keys only; nothing else leaves the page). */
  onFaceFit?: (hints: FaceFitHint[], shape: FaceShapeReading | null) => void;
  /** Jawline shading state (default / analyzing / personalized / fallback); the default shading shows in all of them. */
  onFaceFitStatus?: (status: FaceFitStatus) => void;
  /** The WebView's renderer process died (out of memory / GPU reset). Without this the whole app exits. */
  onCrash?: () => void;
  renderCommand?: ArRenderCommand | null;
  onRenderResult?: (result: ArRenderResult) => void;
  /** Development only (AR_SPEC 1-4, 11-02): record the AR canvas while true. Ignored in a production build. */
  recording?: boolean;
  /** Development only: pieces and state of the recording above. */
  onRecorder?: (message: RecorderMessage) => void;
}

export function ArFaceView({ makeup, compare, guide = null, fillPreview = false, recording = false, onStatus, onLightHint, onSkinTone, onFaceFit, onFaceFitStatus, onCrash, onRecorder, renderCommand = null, onRenderResult }: ArFaceViewProps) {
  // react-native-webview의 타입이 제네릭 기본값을 `never`로 잡는 경우가 있어,
  // 메시지/소스에 대해 넉넉한 타입을 명시해 props 타입 추론을 정상화합니다.
  const ref = useRef<WebView<any>>(null);
  const stateSeq = useRef(0);
  const latest = useRef({ makeup, compare, guide, fillPreview, onLightHint, onSkinTone, onFaceFit, onFaceFitStatus, onCrash, onRecorder, renderCommand, onRenderResult });
  useEffect(() => {
    latest.current = { makeup, compare, guide, fillPreview, onLightHint, onSkinTone, onFaceFit, onFaceFitStatus, onCrash, onRecorder, renderCommand, onRenderResult };
  });

  // The recorder is not part of the page: in development it is injected when recording starts (components/ar/recorderScript.ts).
  const wasRecording = useRef(false);
  useEffect(() => {
    if (!__DEV__ || recording === wasRecording.current) return;
    wasRecording.current = recording;
    if (recording) {
      import('./recorderScript').then(({ AR_RECORDER_SCRIPT }) =>
        ref.current?.injectJavaScript(`${AR_RECORDER_SCRIPT}\nwindow.__kbRec && window.__kbRec.start(); true;`)
      );
    } else {
      ref.current?.injectJavaScript('window.__kbRec && window.__kbRec.stop(); true;');
    }
  }, [recording]);

  const send = useCallback((message: object) => {
    const payload = JSON.stringify(JSON.stringify(message));
    ref.current?.injectJavaScript(`window.__kb && window.__kb.receive(${payload}); true;`);
  }, []);

  const sendMakeup = useCallback((current: MakeupState, command: ArRenderCommand | null) => {
    const sequence = ++stateSeq.current;
    send(command ? { type: command.kind === 'restore' ? 'restore_command' : 'render_command', ...command, stateSeq: sequence }
      : { type: 'makeup', makeup: current, stateSeq: sequence });
  }, [send]);

  useEffect(() => {
    sendMakeup(makeup, renderCommand);
  }, [makeup, renderCommand, sendMakeup]);
  useEffect(() => send({ type: 'compare', value: compare }), [compare, send]);
  useEffect(() => send({ type: 'guide', guide }), [guide, send]);
  useEffect(() => send({ type: 'preview', fill: fillPreview }), [fillPreview, send]);

  const onMessage = (event: WebViewMessageEvent) => {
    let message: { type?: string; status?: string; detail?: string; value?: LightHint | null; lab?: unknown; conf?: unknown; rec?: unknown; state?: unknown; shape?: unknown; commandId?: unknown; restoreId?: unknown; renderSeq?: unknown; rendererId?: unknown };
    try {
      message = JSON.parse(event.nativeEvent.data);
    } catch {
      return;
    }
    if (message.type === 'hello') {
      const command = latest.current.renderCommand;
      sendMakeup(latest.current.makeup, command);
      send({ type: 'compare', value: latest.current.compare });
      send({ type: 'guide', guide: latest.current.guide });
      send({ type: 'preview', fill: latest.current.fillPreview });
    } else if (message.type === 'render_result') {
      const command = latest.current.renderCommand;
      if (command && command.kind !== 'restore' && message.commandId === command.commandId && message.renderSeq === command.renderSeq &&
          message.rendererId === command.rendererId && (message.status === 'rendered' || message.status === 'failed')) {
        latest.current.onRenderResult?.({ commandId: command.commandId, renderSeq: command.renderSeq, rendererId: command.rendererId, status: message.status });
      }
    } else if (message.type === 'restore_result') {
      const command = latest.current.renderCommand;
      if (command?.kind === 'restore' && command.restoreId && message.commandId === command.commandId &&
          message.restoreId === command.restoreId && message.renderSeq === command.renderSeq &&
          message.rendererId === command.rendererId && (message.status === 'rendered' || message.status === 'failed')) {
        latest.current.onRenderResult?.({ commandId: command.commandId, kind: 'restore', restoreId: command.restoreId,
          renderSeq: command.renderSeq, rendererId: command.rendererId, status: message.status });
      }
    } else if (message.type === 'status' && message.status) {
      if (__DEV__ && message.detail) console.warn('[ar]', message.status, message.detail);
      onStatus(message.status as ArStatus);
    } else if (message.type === 'light_hint') {
      const hint = message.value === 'low' || message.value === 'blown' ? message.value : null;
      latest.current.onLightHint?.(hint);
    } else if (message.type === 'skin_tone') {
      const tone = parseSkinTone(message);
      if (tone) latest.current.onSkinTone?.(tone);
    } else if (message.type === 'face_fit') {
      const hints = parseFaceFit(message);
      if (hints) latest.current.onFaceFit?.(hints, parseFaceShape(message));
    } else if (message.type === 'face_fit_status') {
      const status = parseFaceFitStatus(message);
      if (status) latest.current.onFaceFitStatus?.(status);
    } else if (message.type === 'crash') {
      latest.current.onCrash?.();
    } else if (__DEV__ && typeof message.type === 'string' && message.type.startsWith('rec_')) {
      const recorded = parseRecorderMessage(message);
      if (recorded) latest.current.onRecorder?.(recorded);
    }
  };

  return (
    <WebView<any>
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
      onRenderProcessGone={() => latest.current.onCrash?.()}
      onContentProcessDidTerminate={() => latest.current.onCrash?.()}
      webviewDebuggingEnabled={__DEV__}
      style={styles.webview}
      containerStyle={styles.webview}
    />
  );
}

const styles = StyleSheet.create({
  webview: { flex: 1, backgroundColor: '#000' },
});
