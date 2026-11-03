import { useCallback, useEffect, useRef, useState } from 'react';
import { RecordingSink, shareRecording, type RecorderMessage } from '@/lib/arRecording';

export type RecordingState = 'idle' | 'starting' | 'recording' | 'saving';
export type RecordingFailure = 'unsupported' | 'failed' | 'share';

/**
 * Development-only AR screen recording (AR_SPEC 1-4, 11-02 exception). `available` is false in a production build, so the
 * screen shows no button and the page never receives the recorder. The clip is written to this device's cache and handed
 * to the share sheet; nothing is uploaded.
 */
export function useArRecording(onFail: (reason: RecordingFailure) => void) {
  const available = __DEV__;
  const [state, setState] = useState<RecordingState>('idle');
  const [wanted, setWanted] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const sink = useRef<RecordingSink | null>(null);
  const startedAt = useRef(0);
  const onFailRef = useRef(onFail);
  useEffect(() => {
    onFailRef.current = onFail;
  });

  const reset = useCallback(() => {
    sink.current?.discard();
    sink.current = null;
    setWanted(false);
    setState('idle');
  }, []);

  const toggle = useCallback(() => {
    if (!available) return;
    if (state === 'idle') {
      setWanted(true);
      setState('starting');
    } else if (wanted) {
      // Stop: the page sends rec_done after its last piece, which moves on to saving.
      setWanted(false);
      if (state === 'recording') setState('saving');
    }
  }, [available, state, wanted]);

  const handleMessage = useCallback(
    (m: RecorderMessage) => {
      if (!available) return;
      if (m.type === 'rec_state') {
        sink.current?.discard();
        sink.current = new RecordingSink(m.mime);
        startedAt.current = Date.now();
        setState('recording');
      } else if (m.type === 'rec_chunk') {
        sink.current?.append(m.data);
      } else if (m.type === 'rec_done') {
        const current = sink.current;
        sink.current = null;
        setWanted(false);
        setState('saving');
        if (!current) {
          reset();
          return;
        }
        current
          .finish(m.bytes)
          .then(async ({ uri }) => {
            if (!(await shareRecording(uri, m.mime))) onFailRef.current('share');
          })
          .catch((e) => {
            console.warn('[ar-rec]', e);
            current.discard();
            onFailRef.current('failed');
          })
          .finally(() => setState('idle'));
      } else if (m.type === 'rec_error') {
        console.warn('[ar-rec]', m.detail);
        reset();
        onFailRef.current(m.detail === 'unsupported' ? 'unsupported' : 'failed');
      }
    },
    [available, reset]
  );

  useEffect(() => {
    if (state !== 'recording') {
      setSeconds(0);
      return;
    }
    const timer = setInterval(() => setSeconds(Math.floor((Date.now() - startedAt.current) / 1000)), 500);
    return () => clearInterval(timer);
  }, [state]);

  // Leaving the AR screen ends the page; a half-written clip is dropped.
  useEffect(() => () => void sink.current?.discard(), []);

  return { available, state, wanted, seconds, toggle, handleMessage };
}
