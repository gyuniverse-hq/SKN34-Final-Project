import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { AppState } from 'react-native';
import { analyzeSkin, cancelSkinAnalysis, onSkinProgress, createSkinWebRun, skinAnalysisUsesWebView, skinAnalysisServerMode } from '@/lib/skinAnalysis';
import { SkinCaptureAssembler } from '@/lib/skinCapture';
import { skinApiUrl, uploadSkinPhoto } from '@/lib/skinServer';
import { appendSkinTiming, validateSkinAnalysis } from '@/lib/skinProfile';
import { useSkinProfileStore } from '@/store/skinProfileStore';
import type { SkinAnalysisResult, SkinCameraEvent, SkinIndicator, SkinQuestionnaire, SkinWebRun, SkinWebEvent } from '@/types/skin';

export function useSkinAnalysis() {
  const [phase, setPhase] = useState<'ready' | 'camera' | 'analysis' | 'survey' | 'saving' | 'done' | 'error'>('ready');
  const [camera, setCamera] = useState<SkinCameraEvent>({ guidance: 'noFace', progress: 0 });
  const [indicator, setIndicator] = useState<SkinIndicator>('acne');
  const [result, setResult] = useState<SkinAnalysisResult>();
  const [answers, setAnswers] = useState<Partial<SkinQuestionnaire>>({});
  const [error, setError] = useState<'analysis' | 'storage' | 'model' | 'permission' | 'auth' | 'network' | 'busy' | 'photo' | null>(null);
  const [webRun, setWebRun] = useState<SkinWebRun>();
  const generation = useRef(0);
  const assembly = useRef<SkinCaptureAssembler | null>(null);
  const upload = useRef<AbortController | null>(null);
  const captureClaimed = useRef(false);
  const receivedAt = useRef(0);
  const recorded = useRef('');
  const saving = useRef(false);
  const save = useSkinProfileStore(s => s.save);
  const renderGeneration = generation.current;

  const cancel = useCallback(() => {
    generation.current++;
    assembly.current?.clear(); assembly.current = null;
    upload.current?.abort(); upload.current = null;
    captureClaimed.current = false;
    void cancelSkinAnalysis().catch(() => {});
    setPhase('ready');
    setResult(undefined); setAnswers({}); setError(null);
    setWebRun(undefined);
  }, []);

  useEffect(() => {
    const progress = onSkinProgress(event => setIndicator(event.indicator));
    const app = AppState.addEventListener('change', state => {
      if (state !== 'active' && !saving.current) cancel();
    });
    return () => {
      generation.current++;
      assembly.current?.clear(); assembly.current = null; upload.current?.abort();
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

  const onWebEvent = useCallback((event: SkinWebEvent) => {
    if (!webRun || renderGeneration !== generation.current || !['camera', 'analysis'].includes(phase)) return;
    if (skinAnalysisServerMode && ['capture-start', 'capture-chunk', 'capture-end'].includes(event.type)) {
      if (captureClaimed.current || !assembly.current) return;
      try {
        const photo = assembly.current.push(event as Record<string, unknown>);
        if (!photo) return;
        assembly.current = null; captureClaimed.current = true;
        const current = generation.current, controller = new AbortController();
        upload.current = controller; setPhase('analysis');
        void uploadSkinPhoto(photo, webRun.run, controller.signal).then(next => {
          if (current !== generation.current) return;
          validateSkinAnalysis(next); receivedAt.current = performance.now();
          setResult(next); setPhase('survey');
        }).catch((failure: { code?: string }) => {
          if (current !== generation.current) return;
          setError(failure?.code === 'UNAUTHORIZED' ? 'auth' : failure?.code === 'SERVER_BUSY' ? 'busy'
            : ['FACE_NOT_FOUND', 'MULTIPLE_FACES', 'FACE_OUT_OF_BOUNDS', 'INVALID_IMAGE', 'INVALID_RESULT'].includes(failure?.code || '') ? 'photo' : 'network');
          setPhase('error');
        }).finally(() => { photo.bytes.fill(0); if (upload.current === controller) upload.current = null; });
      } catch { assembly.current?.clear(); assembly.current = null; setError('photo'); setPhase('error'); }
      return;
    }
    if (event.type === 'camera' && phase === 'camera') setCamera(event.state);
    else if (event.type === 'captured') setPhase('analysis');
    else if (event.type === 'progress') setIndicator(event.indicator);
    else if (event.type === 'error') {
      setError(event.code === 'permission' ? 'permission' : event.code === 'model' ? 'model' : 'analysis');
      setPhase('error');
    } else if (event.type === 'result' && !skinAnalysisServerMode) {
      try {
        validateSkinAnalysis(event.result);
        receivedAt.current = performance.now(); setResult(event.result); setPhase('survey');
      } catch { setError('model'); setPhase('error'); }
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
    upload.current?.abort(); upload.current = null;
    assembly.current?.clear(); assembly.current = null;
    await cancelSkinAnalysis().catch(() => {});
    if (current !== generation.current) return;
    captureClaimed.current = false;
    setAnswers({}); setResult(undefined); setError(null);
    setCamera({ guidance: 'noFace', progress: 0 });
    try {
      if (skinAnalysisServerMode) skinApiUrl(process.env.EXPO_PUBLIC_SKIN_API_URL);
      const run = skinAnalysisUsesWebView ? createSkinWebRun() : undefined;
      assembly.current = run?.mode === 'server' ? new SkinCaptureAssembler(run.run.runId + ':jpeg') : null;
      setWebRun(run); setPhase('camera');
    } catch { setError('network'); setPhase('error'); }
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

  return { phase, camera, indicator, answers, setAnswers, error, complete, start, onCapture, finish, cancel, webRun, onWebEvent };
}
