import { createElement, useCallback, useEffect, useRef, useState } from 'react';
import { parseSkinTone } from '@/lib/foundationMatch';
import type { ArFaceViewProps, LightHint } from './ArFaceView';
import { FACE_TRACKER_HTML, type ArStatus } from './faceTrackerHtml';

export function ArFaceView({ makeup, compare, guide = null, fillPreview = false, onStatus, onLightHint, onSkinTone, renderCommand = null, onRenderResult }: ArFaceViewProps) {
  const [frame, setFrame] = useState<HTMLIFrameElement | null>(null);
  const stateSeq = useRef(0);
  const latest = useRef({ makeup, compare, guide, fillPreview, onStatus, onLightHint, onSkinTone, renderCommand, onRenderResult });
  useEffect(() => {
    latest.current = { makeup, compare, guide, fillPreview, onStatus, onLightHint, onSkinTone, renderCommand, onRenderResult };
  });

  const send = useCallback(
    (message: object) => frame?.contentWindow?.postMessage(JSON.stringify(message), '*'),
    [frame]
  );

  const sendMakeup = useCallback((current: ArFaceViewProps['makeup'], command: ArFaceViewProps['renderCommand']) => {
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

  useEffect(() => {
    if (!frame) return;
    const onMessage = (event: MessageEvent) => {
      if (event.source !== frame.contentWindow || typeof event.data !== 'string') return;
      let message: { type?: string; status?: string; value?: LightHint | null; lab?: unknown; conf?: unknown; commandId?: unknown; restoreId?: unknown; renderSeq?: unknown; rendererId?: unknown };
      try {
        message = JSON.parse(event.data);
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
        latest.current.onStatus(message.status as ArStatus);
      } else if (message.type === 'light_hint') {
        const hint = message.value === 'low' || message.value === 'blown' ? message.value : null;
        latest.current.onLightHint?.(hint);
      } else if (message.type === 'skin_tone') {
        const tone = parseSkinTone(message);
        if (tone) latest.current.onSkinTone?.(tone);
      }
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [frame, send, sendMakeup]);

  return createElement('iframe', {
    ref: setFrame,
    srcDoc: FACE_TRACKER_HTML,
    allow: 'camera; autoplay',
    title: 'AR try-on',
    style: { border: 0, width: '100%', height: '100%', backgroundColor: '#000' },
  });
}
