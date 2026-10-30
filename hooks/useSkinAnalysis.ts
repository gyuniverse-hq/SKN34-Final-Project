import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { AppState } from 'react-native';
import { analyzeSkin, cancelSkinAnalysis, onSkinProgress, createSkinWebRun, skinAnalysisUsesWebView } from '@/lib/skinAnalysis';
import { appendSkinTiming, validateSkinAnalysis } from '@/lib/skinProfile';
import { useSkinProfileStore } from '@/store/skinProfileStore';
import { useSkinPreviewStore } from '@/store/skinPreviewStore';
import { SkinPreviewAssembler } from '@/lib/skinPreview';
import type { SkinAnalysisResult, SkinCameraEvent, SkinIndicator, SkinQuestionnaire, SkinWebRun, SkinWebEvent, SkinPreview } from '@/types/skin';

export function useSkinAnalysis() {
  const [phase, setPhase] = useState<'ready' | 'camera' | 'analysis' | 'survey' | 'saving' | 'done' | 'error'>('ready');
  const [camera, setCamera] = useState<SkinCameraEvent>({ guidance: 'noFace', progress: 0 });
  const [indicator, setIndicator] = useState<SkinIndicator>('acne');
  const [result, setResult] = useState<SkinAnalysisResult>();
  const [answers, setAnswers] = useState<Partial<SkinQuestionnaire>>({});
  const [error, setError] = useState<'analysis' | 'storage' | 'model' | 'permission' | null>(null);
  const [webRun, setWebRun] = useState<SkinWebRun>();
  const generation = useRef(0);
  const previewAssembler = useRef<SkinPreviewAssembler | null>(null);
  const pendingPreview = useRef<SkinPreview | null>(null);
  const previewTransferred = useRef(false);
  const captureClaimed = useRef(false);
  const receivedAt = useRef(0);
  const recorded = useRef('');
  const saving = useRef(false);
  const save = useSkinProfileStore(s => s.save);
  const renderGeneration = generation.current;

  const cancel = useCallback(() => {
    generation.current++;
    previewAssembler.current?.clear(); previewAssembler.current = null; pendingPreview.current = null;
    previewTransferred.current = false; useSkinPreviewStore.getState().clear();
    captureClaimed.current = false;
    void cancelSkinAnalysis().catch(() => {});
    setPhase('ready');
    setResult(undefined); setAnswers({}); setError(null);
    setWebRun(undefined);
  }, []);

  useEffect(() => {
    const progress = onSkinProgress(event => setIndicator(event.indicator));
    const app = AppState.addEventListener('change', state => {
      if (state !== 'active') {
        if (!saving.current) cancel();
        else {
          previewAssembler.current?.clear(); previewAssembler.current = null; pendingPreview.current = null;
          useSkinPreviewStore.getState().clear();
        }
      }
    });
    return () => {
      generation.current++;
      previewAssembler.current?.clear(); previewAssembler.current = null; pendingPreview.current = null;
      if (!previewTransferred.current) useSkinPreviewStore.getState().clear();
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
    void analyzeSkin(event.captureId).then(response => {
      if (current !== generation.current) return;
      const { preview, ...next } = response;
      validateSkinAnalysis(next);
      if (preview) {
        try {
          const receiver = new SkinPreviewAssembler(next.timing.runId);
          receiver.push({ type: 'preview-start', runId: next.timing.runId, width: preview.width,
            height: preview.height, outline: preview.outline, boxes: preview.boxes, length: preview.jpeg.length });
          for (let i = 0; i < preview.jpeg.length; i += 48 * 1024) {
            receiver.push({ type: 'preview-chunk', runId: next.timing.runId, index: i / (48 * 1024), data: preview.jpeg.slice(i, i + 48 * 1024) });
          }
          pendingPreview.current = receiver.push({ type: 'preview-end', runId: next.timing.runId }) ?? null;
        } catch { pendingPreview.current = null; }
      }
      receivedAt.current = performance.now();
      setResult(next); setPhase('survey');
    }).catch((failure: { code?: string }) => {
      if (current === generation.current) { setError(failure?.code === 'ERR_SKIN_MODEL' ? 'model' : 'analysis'); setPhase('error'); }
    });
  }, [phase, renderGeneration]);

  const onWebEvent = useCallback((event: SkinWebEvent) => {
    if (!webRun || renderGeneration !== generation.current || !['camera', 'analysis'].includes(phase)) return;
    if (event.type === 'preview-start' || event.type === 'preview-chunk' || event.type === 'preview-end') {
      try { pendingPreview.current = previewAssembler.current?.push(event) ?? pendingPreview.current; }
      catch { previewAssembler.current?.clear(); previewAssembler.current = null; pendingPreview.current = null; }
      return;
    }
    if (event.type === 'camera' && phase === 'camera') setCamera(event.state);
    else if (event.type === 'captured') setPhase('analysis');
    else if (event.type === 'progress') setIndicator(event.indicator);
    else if (event.type === 'error') {
      previewAssembler.current?.clear(); previewAssembler.current = null; pendingPreview.current = null;
      setError(event.code === 'permission' ? 'permission' : event.code === 'model' ? 'model' : 'analysis');
      setPhase('error');
    } else if (event.type === 'result') {
      try {
        if (event.result.timing.runId !== webRun.run.runId) throw new Error('Invalid run');
        if (event.result.schema !== 'skin-analysis-mobile-v1') throw new Error('Invalid on-device result');
        validateSkinAnalysis(event.result);
        receivedAt.current = performance.now(); setResult(event.result); setPhase('survey');
      } catch { previewAssembler.current?.clear(); pendingPreview.current = null; setError('model'); setPhase('error'); }
    }
  }, [webRun, phase, renderGeneration]);

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
    previewAssembler.current?.clear(); previewAssembler.current = null; pendingPreview.current = null;
    previewTransferred.current = false; useSkinPreviewStore.getState().clear();
    await cancelSkinAnalysis().catch(() => {});
    if (current !== generation.current) return;
    captureClaimed.current = false;
    setAnswers({}); setResult(undefined); setError(null);
    setCamera({ guidance: 'noFace', progress: 0 });
    try {
      const run = skinAnalysisUsesWebView ? createSkinWebRun() : undefined;
      previewAssembler.current = run ? new SkinPreviewAssembler(run.run.runId) : null;
      setWebRun(run); setPhase('camera');
    } catch {
      setError('model'); setPhase('error');
    }
  };

  const complete = answers.tightness !== undefined && answers.oiliness !== undefined && answers.sensitivity !== undefined;
  const finish = async () => {
    if (!result || !complete || saving.current) return;
    saving.current = true;
    setPhase('saving'); setError(null);
    try {
      await appendSkinTiming(result.timing);
      await save({ version: 1, registeredAt: new Date().toISOString(), analysis: result, questionnaire: answers as SkinQuestionnaire });
      if (pendingPreview.current?.runId === result.timing.runId) {
        useSkinPreviewStore.getState().setPreview(pendingPreview.current);
        previewTransferred.current = true;
      }
      pendingPreview.current = null; previewAssembler.current?.clear(); previewAssembler.current = null;
      setPhase('done');
    } catch { setError('storage'); setPhase('survey'); }
    finally { saving.current = false; }
  };

  return { phase, camera, indicator, result, answers, setAnswers, error, complete, start, onCapture, finish, cancel, webRun, onWebEvent };
}
