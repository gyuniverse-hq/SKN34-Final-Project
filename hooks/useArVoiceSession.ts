import { useCallback, useEffect, useRef, useState } from 'react';
import { Alert } from 'react-native';
import { apiPostOwned, subscribeArIdentityChange, type ArRequestOwner } from '@/lib/api';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import type { ControlScreen } from '@/lib/arControl';
import { useMakeupStore } from '@/store/makeupStore';
import type { VoiceToolCall } from './useArCommand';

const configured = process.env.EXPO_PUBLIC_AR_VOICE_MODEL;
export const integratedVoiceModel = __DEV__ && (configured === 'gpt-realtime-2.1-mini' || configured === 'gpt-live-1') ? configured : null;
type Session = { controller: AbortController; screen: ControlScreen; version: number; owner?: ArRequestOwner; used?: boolean };
type Phase = 'idle' | 'preparing' | 'recording' | 'thinking' | 'speaking';

export function useArVoiceSession(active: boolean, screen: ControlScreen,
  send: (text: string, signal: AbortSignal, call: VoiceToolCall) => Promise<string | undefined>) {
  const { t } = useI18n();
  const [phase, setPhase] = useState<Phase>('idle');
  const [notice, setNotice] = useState<TranslationKey | null>(null);
  const [mounted, setMounted] = useState(false);
  const session = useRef<Session | null>(null);
  const consent = useRef(false);
  const stop = useCallback(() => {
    session.current?.controller.abort(); session.current = null;
    setMounted(false); setPhase('idle');
  }, []);
  useEffect(() => {
    if (!active || !integratedVoiceModel) return;
    const unsubscribe = subscribeArIdentityChange(stop);
    return () => { unsubscribe(); stop(); };
  }, [active, stop]);
  const failed = () => { setNotice('ar.voice.failed'); stop(); };
  const microphone = () => {
    if (session.current) { stop(); return; }
    if (!active || !integratedVoiceModel) return;
    const run: Session = { controller: new AbortController(), screen, version: useMakeupStore.getState().arVersion };
    session.current = run;
    const start = async () => {
      if (session.current !== run) return;
      consent.current = true; setNotice(null); setPhase('preparing');
      try {
        const { requestRecordingPermissionsAsync } = require('expo-audio') as typeof import('expo-audio');
        const permission = await requestRecordingPermissionsAsync();
        if (session.current !== run) return;
        if (!permission.granted) { stop(); setNotice('ar.voice.permission'); return; }
        setMounted(true);
      } catch { if (session.current === run) failed(); }
    };
    if (consent.current) void start();
    else Alert.alert(t('ar.voice.start'), t('ar.voice.liveConsent'), [
      { text: t('common.cancel'), onPress: stop }, { text: t('ar.voice.start'), onPress: () => void start() },
    ], { cancelable: false });
  };
  const onOffer = async (sdp: string) => {
    const run = session.current;
    if (!run) throw new Error('Session ended');
    const { data, owner } = await apiPostOwned<{sdp: string}>('/api/chat/ar-control/voice-session', {
      model: integratedVoiceModel, sdp, screen: { choices: [...run.screen.choices.keys()], summary: run.screen.summary },
    }, { signal: run.controller.signal });
    if (session.current !== run) throw new Error('Session ended');
    run.owner = owner;
    return data.sdp;
  };
  const onTool = async (args: Record<string, unknown>) => {
    const run = session.current;
    if (!run?.owner || run.used || typeof args.choice !== 'string' || !run.screen.choices.has(args.choice)) return;
    run.used = true;
    if ((args.steps != null && (typeof args.steps !== 'number' || !Number.isInteger(args.steps) || args.steps < 1 || args.steps > 100)) ||
        (args.value != null && (typeof args.value !== 'number' || !Number.isFinite(args.value) || args.value < 0 || args.value > 1.7))) return;
    return send('', run.controller.signal, { args, owner: run.owner, stateVersion: run.version, contextKey: run.screen.contextKey });
  };
  return { microphone, mounted, phase, notice, onOffer, onTool, onPhase: setPhase, onFailure: failed, onEnd: stop };
}
