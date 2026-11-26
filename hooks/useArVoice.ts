import { useEffect, useRef, useState } from 'react';
import { Alert, Platform } from 'react-native';
import type { AudioRecorder } from 'expo-audio';
import { File } from 'expo-file-system';
import * as Speech from 'expo-speech';
import { apiPostOwned, subscribeArIdentityChange } from '@/lib/api';
import { encodeArVoiceContext } from '@/lib/arVoiceContext';
import { useI18n, type Language, type TranslationKey } from '@/lib/i18n';

type Phase = 'idle' | 'preparing' | 'recording' | 'hearing' | 'transcribing' | 'thinking' | 'speaking' | 'ending';
type Audio = typeof import('expo-audio');
const MAX_SEGMENT_MS = 30_000;
const QUIET_MS = 1_200;
const SAMPLE_MS = 100;
const TRANSCRIPTION_TIMEOUT_MS = 15_000;
const SPEECH_LOCALES: Record<Language, string> = { en: 'en-US', ko: 'ko-KR', ja: 'ja-JP', zh: 'zh-CN' };

class MeterUnavailable extends Error {}
class TranscriptionTimeout extends Error {}

async function beforeDeadline<T>(work: Promise<T>, expiresAt: number, signal: AbortSignal): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let cancel: (() => void) | undefined;
  try {
    return await Promise.race([
      work,
      new Promise<never>((_, reject) => {
        cancel = () => reject(new Error('Voice session ended'));
        signal.addEventListener('abort', cancel);
        if (signal.aborted) cancel();
        timer = setTimeout(() => reject(new TranscriptionTimeout()), Math.max(0, expiresAt - Date.now()));
      }),
    ]);
  } finally {
    clearTimeout(timer);
    if (cancel) signal.removeEventListener('abort', cancel);
  }
}

// Native meters report dBFS. Compare sustained levels to this room and utterance.
function waitForUtterance(recorder: AudioRecorder, signal: AbortSignal, onSpeech: () => void): Promise<number> {
  return new Promise((resolve, reject) => {
    const start = Date.now();
    const recent: number[] = [];
    let floor: number | undefined;
    let peak = -160;
    let lastMeter = start;
    let lastSpeech = 0;
    let timer: ReturnType<typeof setInterval>;
    function finish(hasSpeech: boolean, error?: Error) {
      clearInterval(timer);
      signal.removeEventListener('abort', cancel);
      if (error) reject(error);
      else resolve(hasSpeech ? lastSpeech : 0);
    }
    function cancel() { finish(false); }
    timer = setInterval(() => {
      try {
        const { metering, isRecording } = recorder.getStatus();
        const now = Date.now();
        if (!isRecording && now - start > 500) {
          finish(false, new Error('Recording interrupted'));
          return;
        }
        if (typeof metering === 'number' && (Number.isFinite(metering) || metering === -Infinity)) {
          lastMeter = now;
          recent.push(Math.max(-160, metering));
          if (recent.length > 3) recent.shift();
          if (recent.length === 3) {
            const level = [...recent].sort((a, b) => a - b)[1];
            floor ??= level;
            if (!lastSpeech) {
              const rising = level >= Math.max(-65, floor + 8);
              // Someone may already be talking when the first samples arrive.
              const falling = floor >= -65 && level <= floor - 10;
              if (rising || falling) {
                peak = Math.max(floor, level);
                floor = Math.min(floor, level);
                lastSpeech = falling ? now - SAMPLE_MS : now;
                onSpeech();
              } else {
                floor += (level - floor) * 0.12;
              }
            } else if (level >= Math.max(-68, floor + 4, peak - 12)) {
              peak = Math.max(level, peak - 0.4);
              lastSpeech = now;
            }
          }
        } else if (now - lastMeter >= 1500) {
          finish(false, new MeterUnavailable());
          return;
        }
        if ((lastSpeech && now - lastSpeech >= QUIET_MS) || now - start >= MAX_SEGMENT_MS) {
          finish(lastSpeech > 0);
        }
      } catch {
        finish(false, new Error('Recorder unavailable'));
      }
    }, SAMPLE_MS);
    signal.addEventListener('abort', cancel);
    if (signal.aborted) cancel();
  });
}

async function capture(audio: Audio, signal: AbortSignal, setPhase: (phase: Phase) => void) {
  const options = { ...audio.RecordingPresets.HIGH_QUALITY, numberOfChannels: 1, bitRate: 64000, isMeteringEnabled: true };
  let recorder: AudioRecorder | undefined;
  let started = false;
  let uri: string | null = null;
  let expiresAt: number | undefined;
  await audio.setAudioModeAsync({ allowsRecording: true, playsInSilentMode: true });
  try {
    if (signal.aborted) return;
    recorder = new audio.AudioModule.AudioRecorder({ ...options, ...(Platform.OS === 'ios' ? options.ios : options.android) });
    await recorder.prepareToRecordAsync(options);
    uri = recorder.uri;
    if (signal.aborted) return;
    recorder.record({ forDuration: 31 });
    started = true;
    setPhase('recording');
    const hasSpeech = await waitForUtterance(recorder, signal, () => setPhase('hearing'));
    expiresAt = Date.now() + TRANSCRIPTION_TIMEOUT_MS;
    if (hasSpeech && !signal.aborted) setPhase('transcribing');
    started = false;
    await beforeDeadline(recorder.stop(), expiresAt, signal);
    uri = recorder.uri ?? uri;
    if (signal.aborted || !hasSpeech) return;
    if (!uri) throw new Error('Missing recording');
    const bytes = await beforeDeadline(new File(uri).arrayBuffer(), expiresAt, signal);
    return { bytes, expiresAt, speechEnd: hasSpeech };
  } finally {
    try {
      if (started && recorder) {
        await beforeDeadline(recorder.stop(), Date.now() + TRANSCRIPTION_TIMEOUT_MS, signal).catch(() => {});
      }
      uri = recorder?.uri ?? uri;
      recorder?.release();
      if (uri) {
        const file = new File(uri);
        if (file.exists) file.delete();
      }
    } finally {
      await beforeDeadline(audio.setAudioModeAsync({ allowsRecording: false }),
        expiresAt ?? Date.now() + TRANSCRIPTION_TIMEOUT_MS, signal);
    }
  }
}

export function useArVoice(
  active: boolean,
  onTranscript: (text: string, signal: AbortSignal, onPainted?: () => void) => Promise<string | undefined>,
  getKeywords: () => readonly string[],
) {
  const { t, language } = useI18n();
  const available = Platform.OS === 'ios' || Platform.OS === 'android';
  const enabled = active && available;
  const [phase, setPhase] = useState<Phase>('idle');
  const [notice, setNotice] = useState<TranslationKey | null>(null);
  const [muted, setMuted] = useState(false);
  const consent = useRef(false);
  const generation = useRef(0);
  const session = useRef<AbortController | null>(null);
  const output = useRef(true);
  const finishSpeech = useRef<(() => void) | null>(null);
  const send = useRef(onTranscript);
  const keywordsForTurn = useRef(getKeywords);
  send.current = onTranscript;
  keywordsForTurn.current = getKeywords;

  function stopSpeech() {
    const done = finishSpeech.current;
    if (done) return Speech.stop().catch(() => {}).finally(done);
  }

  function end() {
    generation.current++;
    session.current?.abort();
    stopSpeech();
    setPhase(session.current ? 'ending' : 'idle');
  }

  useEffect(() => {
    if (!enabled) return;
    setNotice(null);
    const unsubscribe = subscribeArIdentityChange(end);
    return () => { unsubscribe(); end(); };
  }, [enabled, language]);

  function speak(text: string, onStart?: () => void) {
    return new Promise<void>((resolve) => {
      const done = () => {
        if (finishSpeech.current === done) finishSpeech.current = null;
        resolve();
      };
      finishSpeech.current = done;
      const failed = () => {
        if (finishSpeech.current === done) setNotice('ar.voice.speechFailed');
        done();
      };
      try {
        Speech.speak(text, { language: SPEECH_LOCALES[language], onStart, onDone: done, onStopped: done, onError: failed });
      } catch { failed(); }
    });
  }

  async function run() {
    if (session.current) return;
    const controller = new AbortController();
    const { signal } = controller;
    session.current = controller;
    setNotice(null);
    setPhase('preparing');
    try {
      const audio: Audio = require('expo-audio');
      await stopSpeech();
      if (signal.aborted) return;
      const permission = await audio.requestRecordingPermissionsAsync();
      if (signal.aborted) return;
      if (!permission.granted) { setNotice('ar.voice.permission'); return; }
      while (!signal.aborted) {
        const recording = await capture(audio, signal, setPhase);
        if (signal.aborted || !recording) continue;
        const request = new AbortController();
        let text: string | undefined;
        try {
          const { data } = await beforeDeadline(apiPostOwned<{ text: string }>(
            '/api/chat/ar-control/transcribe', recording.bytes, {
              signal: request.signal, transcriptionContext: encodeArVoiceContext(language, keywordsForTurn.current()),
            }),
          recording.expiresAt, signal);
          text = data.text?.trim();
        } finally {
          request.abort();
        }
        if (signal.aborted) return;
        if (!text) throw new Error('Empty transcript');
        setPhase('thinking');
        const elapsed = () => Date.now() - recording.speechEnd;
        let screenMs: number | undefined;
        const answer = await send.current(text, signal, () => {
          screenMs = elapsed();
          if (__DEV__) console.info('[ar-voice-paint]', { screenMs });
        });
        if (!signal.aborted && output.current && answer) {
          setPhase('speaking');
          await speak(answer, () => {
            if (__DEV__) console.info('[ar-voice-timing]', { screenMs, speechMs: elapsed() });
          });
        }
      }
    } catch (error) {
      if (!signal.aborted) {
        if (error instanceof TranscriptionTimeout) setNotice('ar.voice.timeout');
        else setNotice(error instanceof MeterUnavailable ? 'ar.voice.meterUnavailable' : 'ar.voice.failed');
      }
    } finally {
      session.current = null;
      setPhase('idle');
    }
  }

  function microphone() {
    if (session.current) { end(); return; }
    if (!enabled) return;
    if (consent.current) { void run(); return; }
    const turn = generation.current;
    Alert.alert(t('ar.voice.start'), t('ar.voice.consent'), [
      { text: t('common.cancel'), style: 'cancel' },
      { text: t('ar.voice.start'), onPress: () => {
        if (turn === generation.current) { consent.current = true; void run(); }
      } },
    ]);
  }

  function toggleSound() {
    output.current = !output.current;
    setMuted(!output.current);
    if (!output.current) stopSpeech();
  }

  function beginReply() {
    const turn = generation.current;
    stopSpeech();
    return (text: string | undefined) => {
      if (enabled && turn === generation.current && text && output.current && !session.current) void speak(text);
    };
  }

  return { available, phase, notice, muted, microphone, toggleSound, beginReply };
}
