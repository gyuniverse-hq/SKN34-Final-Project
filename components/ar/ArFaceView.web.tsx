import { createElement, useCallback, useEffect, useRef, useState } from 'react';
import type { ArFaceViewProps } from './ArFaceView';
import { FACE_TRACKER_HTML, type ArStatus } from './faceTrackerHtml';

export function ArFaceView({ makeup, compare, guide = null, onStatus }: ArFaceViewProps) {
  const [frame, setFrame] = useState<HTMLIFrameElement | null>(null);
  const latest = useRef({ makeup, compare, guide, onStatus });
  useEffect(() => {
    latest.current = { makeup, compare, guide, onStatus };
  });

  const send = useCallback(
    (message: object) => frame?.contentWindow?.postMessage(JSON.stringify(message), '*'),
    [frame]
  );

  useEffect(() => send({ type: 'makeup', makeup }), [makeup, send]);
  useEffect(() => send({ type: 'compare', value: compare }), [compare, send]);
  useEffect(() => send({ type: 'guide', guide }), [guide, send]);

  useEffect(() => {
    if (!frame) return;
    const onMessage = (event: MessageEvent) => {
      if (event.source !== frame.contentWindow || typeof event.data !== 'string') return;
      let message: { type?: string; status?: ArStatus };
      try {
        message = JSON.parse(event.data);
      } catch {
        return;
      }
      if (message.type === 'hello') {
        send({ type: 'makeup', makeup: latest.current.makeup });
        send({ type: 'compare', value: latest.current.compare });
        send({ type: 'guide', guide: latest.current.guide });
      } else if (message.type === 'status' && message.status) {
        latest.current.onStatus(message.status);
      }
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [frame, send]);

  return createElement('iframe', {
    ref: setFrame,
    srcDoc: FACE_TRACKER_HTML,
    allow: 'camera; autoplay',
    title: 'AR try-on',
    style: { border: 0, width: '100%', height: '100%', backgroundColor: '#000' },
  });
}
