import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { AppState } from 'react-native';
import { analyzeSkin, cancelSkinAnalysis, onSkinProgress } from '@/lib/skinAnalysis';
import { appendSkinTiming, validateSkinAnalysis } from '@/lib/skinProfile';
import { useSkinProfileStore } from '@/store/skinProfileStore';
import type { SkinAnalysisResult, SkinCameraEvent, SkinIndicator, SkinQuestionnaire } from '@/types/skin';

export function useSkinAnalysis() {
  const [phase, setPhase] = useState<'ready' | 'camera' | 'analysis' | 'survey' | 'saving' | 'done' | 'error'>('ready');
  const [camera, setCamera] = useState<SkinCameraEvent>({ guidance: 'noFace', progress: 0 });
  const [indicator, setIndicator] = useState<SkinIndicator>('acne');
  const [result, setResult] = useState<SkinAnalysisResult>();
  const [answers, setAnswers] = useState<Partial<SkinQuestionnaire>>({});
  const [error, setError] = useState<'analysis' | 'storage' | 'model' | null>(null);
  const generation = useRef(0);
  const captureClaimed = useRef(false);
  const receivedAt = useRef(0);
  const recorded = useRef('');
  const saving = useRef(false);
  const save = useSkinProfileStore(s => s.save);
  const renderGeneration = generation.current;

  const cancel = useCallback(() => {
    generation.current++;
    captureClaimed.current = false;
    void cancelSkinAnalysis().catch(() => {});
    setPhase('ready');
    setResult(undefined); setAnswers({}); setError(null);
  }, []);

  useEffect(() => {
    const progress = onSkinProgress(event => setIndicator(event.indicator));
    const app = AppState.addEventListener('change', state => {
      if (state !== 'active' && !saving.current) cancel();
    });
    return () => {
      generation.current++;
      app.remove(); progress?.remove();
      void cancelSkinAnalysis().catch(() => {});
    };
  }, [cancel]);

  const onCapture = useCallback((event: SkinCameraEvent) => {
    if (phase !== 'camera' || renderGeneration !== generation.current || captureClaimed.current) return;
    setCamera(event);
    if (event.guidance === 'cameraError') { setError('analysis'); setPhase('error'); return; }
    if (!event.captureId) return;
    captureClaimed.current = true;
    const current = generation.current;
    setPhase('analysis');
    void analyzeSkin(event.captureId).then(next => {
      if (current !== generation.current) return;
      validateSkinAnalysis(next);
      receivedAt.current = performance.now();
      setResult(next); setPhase('survey');
    }).catch((failure: { code?: string }) => {
      if (current === generation.current) { setError(failure?.code === 'ERR_SKIN_MODEL' ? 'model' : 'analysis'); setPhase('error'); }
    });
  }, [phase, renderGeneration]);

  // Include the JS handoff up to the first survey layout in the user-visible wait.
  useLayoutEffect(() => {
    if (phase !== 'survey' || !result || recorded.current === result.timing.runId) return;
    recorded.current = result.timing.runId;
    const next = { ...result, timing: { ...result.timing, totalMs: result.timing.totalMs + performance.now() - receivedAt.current } };
    setResult(next);
    const current = generation.current;
    void appendSkinTiming(next.timing).catch(() => {
      if (current === generation.current) setError('storage');
    });
  }, [phase, result]);

  const start = async () => {
    const current = ++generation.current;
    await cancelSkinAnalysis().catch(() => {});
    if (current !== generation.current) return;
    captureClaimed.current = false;
    setAnswers({}); setResult(undefined); setError(null);
    setCamera({ guidance: 'noFace', progress: 0 });
    setPhase('camera');
  };

  const complete = answers.tightness !== undefined && answers.oiliness !== undefined && answers.sensitivity !== undefined;
  const finish = async () => {
    if (!result || !complete || saving.current) return;
    saving.current = true;
    setPhase('saving'); setError(null);
    try {
      await appendSkinTiming(result.timing);
      await save({ version: 1, registeredAt: new Date().toISOString(), analysis: result, questionnaire: answers as SkinQuestionnaire });
      setPhase('done');
    } catch { setError('storage'); setPhase('survey'); }
    finally { saving.current = false; }
  };

  return { phase, camera, indicator, answers, setAnswers, error, complete, start, onCapture, finish, cancel };
}
