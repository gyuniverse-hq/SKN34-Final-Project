import { uuid } from 'expo';
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { apiPostOwned, subscribeArIdentityChange, type ArRequestOwner } from '@/lib/api';
import { confirmArAck, pendingArAcks, queueArAck, retryArAcks, subscribeArAcks } from '@/lib/arCommandAck';
import { revealedMakeup } from '@/lib/practice';
import { reject, type ConfirmPaint, type ControlResult, type ControlScreen } from '@/lib/arControl';
import { readShadePreference } from '@/lib/arShadePreference';
import type { Language } from '@/lib/i18n';
import { geometryFromStyle } from '@/lib/zoneRecipe';
import { AR_PAINT_ZONES, arPaintMakeup, isArPaintZone, isLookPaintZone, useMakeupStore, type ArOutcome, type ArProposal } from '@/store/makeupStore';
import type { ArRenderCommand, ArRenderResult, MakeupZone, ZoneGeometry } from '@/types';

type Phase = 'idle' | 'interpreting' | 'proposed' | 'applying' | 'applied' | 'no_change' | 'clarification' | 'rejected' | 'failed' | 'unknown';
type RestorePhase = 'idle' | 'pending' | 'confirmed' | 'failed' | 'unknown' | 'unavailable';
export type VoiceToolCall = { args: Record<string, unknown>; owner: ArRequestOwner; stateVersion: number; contextKey: string };
type Command = { requestId: string; sessionId: string; owner: ArRequestOwner; proposal: ArProposal; renderSeq: number; rendererId: string; authEpoch: number };
type Restore = { cmd: Command; restoreId: string; renderSeq: number; rendererId: string; stateVersion: number; displayKey: string };
type Options = { active: boolean; enabled: boolean; activeZone: MakeupZone; locale: Language; rendererId: string;
  visibleZones?: MakeupZone[] | null; control?: ControlScreen; fallbackText?: (outcome: ControlResult) => string;
  preview?: (makeup: ArRenderCommand['makeup'], strength?: number, modified?: MakeupZone[]) => ArRenderCommand['makeup'] };
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const RENDER_TIMEOUT_MS = 6000;
const displayKey = (options: Options) => options.visibleZones ? options.visibleZones.join('|') : '*';

function confirmedIntensityChange(choice: string, outcome: ControlResult) {
  if (outcome.status !== 'APPLIED') return;
  const [action, zone, mode] = choice.split('/');
  if (!isArPaintZone(zone as MakeupZone)) return;
  const readIntensity = (layer: unknown) => layer && typeof layer === 'object' &&
    'zone' in layer && layer.zone === zone && 'intensity' in layer ? layer.intensity : undefined;
  const before = readIntensity(outcome.before);
  const after = readIntensity(outcome.after);
  if (typeof before !== 'number' || typeof after !== 'number') return;
  const decreased = (action === 'adjust_intensity' && mode === 'down') || (action === 'set_intensity' && mode === 'half');
  if ((decreased && after < before) || (action === 'adjust_intensity' && mode === 'up' && after > before) ||
      (action === 'set_intensity' && mode === 'absolute' && before !== after)) {
    return { zone: zone as MakeupZone, before, after };
  }
}

function sameGeometry(left: ZoneGeometry, right: unknown): boolean {
  if (!right || typeof right !== 'object') return false;
  return JSON.stringify(left, Object.keys(left).sort()) === JSON.stringify(right, Object.keys(left).sort());
}

function proposalOf(value: unknown): ArProposal | null {
  if (!value || typeof value !== 'object') return null;
  const p = value as Record<string, unknown>;
  if (typeof p.commandId !== 'string' || !UUID.test(p.commandId) ||
      typeof p.expectedStateVersion !== 'number' || !Number.isSafeInteger(p.expectedStateVersion) || p.expectedStateVersion < 0 ||
      typeof p.productId !== 'string' || !p.productId || typeof p.shadeId !== 'string' || !p.shadeId) return null;
  if ((p.action === 'set_intensity' || p.action === 'undo') && isArPaintZone(p.zone as MakeupZone) &&
      typeof p.value === 'number' && Number.isFinite(p.value) && p.value >= 0 && p.value <= 1) {
    return p as unknown as ArProposal;
  }
  if (p.action === 'set_geometry' && typeof p.zone === 'string' && isLookPaintZone(p.zone as MakeupZone) &&
      typeof p.style === 'string' && p.style) {
    const geometry = geometryFromStyle(p.zone as MakeupZone, p.style);
    if (!geometry || !sameGeometry(geometry, p.geometry)) return null;
    return { ...p, geometry } as unknown as ArProposal;
  }
  return null;
}

function zoneSnap(snapshot: ReturnType<typeof useMakeupStore.getState>, zone: MakeupZone) {
  const selected = snapshot.selections[zone];
  const painted = snapshot.makeup[zone];
  return selected && painted ? { productId: selected.productId, shadeId: selected.shadeId, intensity: painted.intensity } : null;
}

export function useArCommand(options: Options) {
  const [state, setState] = useState<Phase>('idle');
  const [applied, setApplied] = useState<ArProposal | null>(null);
  const [message, setMessage] = useState('');
  const [renderCommand, setRenderCommand] = useState<ArRenderCommand | null>(null);
  const [restoreState, setRestoreState] = useState<RestorePhase>('idle');
  const [ackPending, setAckPending] = useState(pendingArAcks);
  const current = useRef(options);
  const session = useRef<string | null>(null);
  const lastAdjustment = useRef<{ commandId: string; version: number; amount: number } | null>(null);
  const command = useRef<Command | null>(null);
  const [controlChoice, setControlChoice] = useState('');
  const [controlResult, setControlResult] = useState<ControlResult | null>(null);
  const frame = useRef<{ id: string; seq: number; renderer: string; finish: (v: Awaited<ReturnType<ConfirmPaint>>) => void } | null>(null);
  const sequence = useRef(0);
  const busy = useRef(false);
  const activeRequest = useRef<string | null>(null);
  const lastRequest = useRef<string | null>(null);
  const executed = useRef(new Map<string, ControlResult>());
  const requestRendererId = useRef<string | null>(null);
  const requestVersion = useRef<number | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const restore = useRef<Restore | null>(null);
  const restoreTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mounted = useRef(false);
  const authEpoch = useRef(0);

  useLayoutEffect(() => { current.current = options; }, [options]);
  useEffect(() => subscribeArAcks(() => setAckPending(pendingArAcks())), []);

  const startRestore = useCallback((cmd: Command) => {
    if (restoreTimer.current) clearTimeout(restoreTimer.current);
    restoreTimer.current = null;
    if (!mounted.current || !current.current.active || current.current.rendererId !== cmd.rendererId) {
      restore.current = null;
      if (mounted.current) { setRestoreState('unavailable'); setRenderCommand(null); }
      return;
    }
    const snapshot = useMakeupStore.getState();
    const pending: Restore = { cmd, restoreId: uuid.v4(), renderSeq: ++sequence.current,
      rendererId: cmd.rendererId, stateVersion: snapshot.arVersion, displayKey: displayKey(current.current) };
    const visibleZones = current.current.visibleZones;
    restore.current = pending;
    setRestoreState('pending');
    setRenderCommand({ kind: 'restore', restoreId: pending.restoreId, commandId: cmd.proposal.commandId,
      renderSeq: pending.renderSeq, rendererId: pending.rendererId,
      makeup: arPaintMakeup(visibleZones ? revealedMakeup(snapshot.makeup, visibleZones) : snapshot.makeup) });
    restoreTimer.current = setTimeout(() => {
      if (restore.current !== pending) return;
      restore.current = null;
      restoreTimer.current = null;
      if (mounted.current) { setRestoreState('unknown'); setRenderCommand(null); }
    }, RENDER_TIMEOUT_MS);
  }, []);

  const complete = useCallback((cmd: Command, outcome: ArOutcome, needsRestore = false) => {
    queueArAck({ requestId: cmd.requestId, commandId: cmd.proposal.commandId, sessionId: cmd.sessionId, ...outcome }, cmd.owner);
    // A reply from a departed session must not cancel a newer session's work.
    if (activeRequest.current !== cmd.requestId) return;
    activeRequest.current = null;
    if (command.current?.proposal.commandId === cmd.proposal.commandId) command.current = null;
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    busy.current = false;
    if (mounted.current) {
      if (needsRestore) startRestore(cmd);
      else { setRenderCommand(null); setRestoreState('idle'); }
      setApplied(outcome.status === 'APPLIED' || outcome.status === 'NO_CHANGE' ? cmd.proposal : null);
      setMessage('');
      setState(outcome.status.toLowerCase() as Phase);
    }
  }, [startRestore]);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  useEffect(() => subscribeArIdentityChange(() => {
    authEpoch.current++;
    lastAdjustment.current = null;
    frame.current?.finish('stale');
    useMakeupStore.setState(s => ({ arUndo: null, tryOnHistory: s.tryOnHistory ? [] : null }));
    if (command.current) useMakeupStore.getState().cancelArCommand();
    else {
      activeRequest.current = null;
      busy.current = false;
      if (mounted.current) { setState('idle'); setMessage(''); }
    }
  }), []);

  useEffect(() => {
    if (!options.active) return;
    const id = uuid.v4();
    session.current = id;
    lastAdjustment.current = null;
    executed.current.clear();
    useMakeupStore.getState().beginArSession(id);
    const unsubscribe = useMakeupStore.subscribe((next, previous) => {
      const restoring = restore.current;
      const pending = previous.pendingArCommand;
      if (pending && !next.pendingArCommand && command.current?.proposal.commandId === pending.proposal.commandId) {
        complete(command.current, { status: 'REJECTED', actualStateVersion: next.arVersion }, true);
      }
      if (frame.current && next.arVersion !== previous.arVersion) frame.current.finish('stale');
      if (!current.current.control && !previous.pendingArCommand && !next.pendingArCommand && activeRequest.current && !command.current &&
          requestVersion.current !== next.arVersion) {
        activeRequest.current = null;
        busy.current = false;
        if (mounted.current) { setState('idle'); setMessage(''); }
      }
      if (restoring && restore.current === restoring && next.arVersion !== previous.arVersion) startRestore(restoring.cmd);
    });
    return () => {
      session.current = null;
      frame.current?.finish('stale');
      if (useMakeupStore.getState().arSessionId === id) useMakeupStore.getState().endArSession();
      if (restore.current) {
        if (restoreTimer.current) clearTimeout(restoreTimer.current);
        restoreTimer.current = null;
        restore.current = null;
        if (mounted.current) setRestoreState('unavailable');
      }
      activeRequest.current = null;
      busy.current = false;
      if (mounted.current) { setState('idle'); setMessage(''); setRenderCommand(null); }
      unsubscribe();
    };
  }, [options.active, complete, startRestore]);

  useLayoutEffect(() => {
    if (restore.current && (!options.active || options.rendererId !== restore.current.rendererId)) {
      if (restoreTimer.current) clearTimeout(restoreTimer.current);
      restoreTimer.current = null;
      restore.current = null;
      setRestoreState('unavailable');
      setRenderCommand(null);
    }
    const cmd = command.current;
    if (cmd && (!options.enabled || options.rendererId !== cmd.rendererId)) {
      useMakeupStore.getState().cancelArCommand();
    }
    if (!options.active || requestRendererId.current !== options.rendererId) frame.current?.finish('stale');
    if (activeRequest.current && (!options.active || (!options.control && !options.enabled) || requestRendererId.current !== options.rendererId)) {
      activeRequest.current = null;
      busy.current = false;
      if (mounted.current) setState('idle');
    }
  }, [options.active, options.enabled, options.rendererId, options.control]);

  useLayoutEffect(() => {
    const pending = restore.current;
    if (pending && pending.displayKey !== displayKey(options)) startRestore(pending.cmd);
  }, [options, startRestore]);

  const onRenderResult = useCallback((result: ArRenderResult) => {
    const controlFrame = frame.current;
    if (controlFrame && result.kind === 'restore' && result.commandId === controlFrame.id &&
        result.restoreId === controlFrame.id && result.renderSeq === controlFrame.seq && result.rendererId === controlFrame.renderer) {
      controlFrame.finish(result.status);
      return;
    }
    if (result.kind === 'restore') {
      const pending = restore.current;
      if (!pending || result.restoreId !== pending.restoreId || result.commandId !== pending.cmd.proposal.commandId ||
          result.rendererId !== pending.rendererId || result.renderSeq !== pending.renderSeq) return;
      if (!current.current.active || current.current.rendererId !== pending.rendererId) return;
      if (useMakeupStore.getState().arVersion !== pending.stateVersion || pending.displayKey !== displayKey(current.current)) {
        startRestore(pending.cmd); return;
      }
      restore.current = null;
      if (restoreTimer.current) clearTimeout(restoreTimer.current);
      restoreTimer.current = null;
      setRenderCommand(null);
      setRestoreState(result.status === 'rendered' ? 'confirmed' : 'failed');
      return;
    }
    const cmd = command.current;
    if (!cmd || result.commandId !== cmd.proposal.commandId || result.rendererId !== cmd.rendererId || result.renderSeq !== cmd.renderSeq) return;
    if (authEpoch.current !== cmd.authEpoch || !current.current.enabled || current.current.rendererId !== cmd.rendererId || session.current !== cmd.sessionId) {
      useMakeupStore.getState().cancelArCommand();
      return;
    }
    // Clear before store mutation: the subscription must not mistake commit for manual cancellation.
    command.current = null;
    const outcome = useMakeupStore.getState().finishArCommand(cmd.proposal.commandId, cmd.sessionId, result.status);
    complete(cmd, outcome, outcome.status !== 'APPLIED' && outcome.status !== 'NO_CHANGE');
  }, [complete, startRestore]);

  const send = useCallback(async (text: string, signal?: AbortSignal, voiceCall?: VoiceToolCall, onPainted?: () => void) => {
    const opts = current.current;
    const sessionId = session.current;
    if ((!text.trim() && !voiceCall) || busy.current || restore.current || (!opts.enabled && !opts.control) || !sessionId) return;
    if (voiceCall && (!opts.control || opts.control.contextKey !== voiceCall.contextKey ||
      useMakeupStore.getState().arVersion !== voiceCall.stateVersion || signal?.aborted)) return;
    setControlChoice('');
    setControlResult(null);
    busy.current = true;
    setMessage('');
    setState('interpreting');
    const requestId = uuid.v4();
    activeRequest.current = lastRequest.current = requestId;
    requestRendererId.current = opts.rendererId;
    const snapshot = useMakeupStore.getState();
    const epoch = authEpoch.current;
    requestVersion.current = snapshot.arVersion;
    let screenKey: 'contextKey' | 'catalogApplyKey' = 'contextKey';
    const isCurrent = () => !signal?.aborted && authEpoch.current === epoch && activeRequest.current === requestId && session.current === sessionId &&
      mounted.current && current.current.active && (opts.control ? current.current.control?.[screenKey] === opts.control[screenKey] : current.current.enabled) &&
      current.current.rendererId === opts.rendererId &&
      useMakeupStore.getState().arVersion === snapshot.arVersion;
    const selections: Partial<Record<MakeupZone, { productId: string; shadeId: string; intensity: number }>> = {};
    for (const zone of AR_PAINT_ZONES) {
      const product = snapshot.selections[zone];
      const layer = snapshot.makeup[zone];
      if (product && layer) selections[zone] = { ...product, intensity: layer.intensity };
    }
    try {
      const prior = lastAdjustment.current;
      const previousAdjustmentId = !voiceCall && opts.control && prior?.version === snapshot.arVersion &&
        await confirmArAck(prior.commandId) ? prior.commandId : undefined;
      if (prior && !isCurrent()) throw new Error('AR screen changed');
      const { data: response, owner } = voiceCall ? {
        data: { answer: '', arResult: { requestId, status: 'proposed', actionProposal: {
          ...voiceCall.args, action: 'ar_control', commandId: uuid.v4(), expectedStateVersion: voiceCall.stateVersion,
        } } }, owner: voiceCall.owner,
      } : await apiPostOwned<{ answer?: unknown; arResult?: unknown }>('/api/chat', {
        message: text.trim(), locale: opts.locale, requestType: 'ar_command', requestId,
        arContext: { screenId: 'A-01', stateVersion: snapshot.arVersion,
          activeZone: isArPaintZone(opts.activeZone) ? opts.activeZone : null,
          supportedActions: opts.control ? ['ar_control'] : ['set_intensity', 'adjust_intensity', 'undo', 'set_geometry'],
          ...(opts.control && { sessionId, previousAdjustmentId,
            ...opts.control.matchCatalog?.(text),
            control: { choices: [...opts.control.choices.keys()], summary: opts.control.summary } }),
          selections, undo: snapshot.arUndo, lip: zoneSnap(snapshot, 'lip'),
          highlighter: zoneSnap(snapshot, 'highlighter'), contour: zoneSnap(snapshot, 'contour'),
          blush: zoneSnap(snapshot, 'blush'), eyeshadow: zoneSnap(snapshot, 'eyeshadow'),
          eyeliner: zoneSnap(snapshot, 'eyeliner'), mascara: zoneSnap(snapshot, 'mascara') },
      }, { timeoutMs: 90_000, signal });
      if (signal?.aborted) throw new Error('Voice conversation ended');
      const ar = response?.arResult;
      if (!ar || typeof ar !== 'object') throw new Error('Invalid AR response');
      const result = ar as Record<string, unknown>;
      if (result.requestId !== requestId || typeof result.status !== 'string') throw new Error('Invalid AR response');
      if (result.status !== 'proposed') {
        if (!['clarification', 'unsupported', 'noop'].includes(result.status)) throw new Error('Invalid AR response');
        if (!isCurrent()) {
          if (activeRequest.current === requestId) {
            activeRequest.current = null;
            busy.current = false;
            setState('rejected');
          }
          return;
        }
        activeRequest.current = null;
        busy.current = false;
        const answer = typeof response.answer === 'string' ? response.answer : '';
        setMessage(answer);
        setState('clarification');
        return answer;
      }
      const tool = result.actionProposal as Record<string, unknown> | undefined;
      if (tool?.action === 'ar_control' && opts.control) {
        if (typeof tool.commandId !== 'string' || !UUID.test(tool.commandId)) throw new Error('Invalid command ID');
        const id = tool.commandId;
        const choice = typeof tool.choice === 'string' ? tool.choice : '';
        if (choice === 'apply_shade/product_pick' || /^apply_shade\/[^/]+\/(pick|by_color|named|oil|balm|skin_match)$/.test(choice)) screenKey = 'catalogApplyKey';
        const operation = opts.control.choices.has(choice) && current.current.control?.choices.get(choice);
        const owned = () => mounted.current && lastRequest.current === requestId && session.current === sessionId && epoch === authEpoch.current;
        let outcome: ControlResult = reject('state changed or operation unavailable');
        const previous = executed.current.get(id);
        const preference = readShadePreference(tool);
        if (previous) outcome = previous;
        else if (isCurrent() && operation && preference && tool.expectedStateVersion === snapshot.arVersion &&
            (tool.name == null || typeof tool.name === 'string') &&
            (tool.value == null || typeof tool.value === 'number' && Number.isFinite(tool.value))) {
          const confirm: ConfirmPaint = (makeup, strength, modified) => new Promise(resolve => {
            if (!isCurrent() || !current.current.enabled) { resolve('stale'); return; }
            const seq = ++sequence.current;
            const finish = (value: Awaited<ReturnType<ConfirmPaint>>) => {
              clearTimeout(timeout);
              frame.current = null;
              if (mounted.current) setRenderCommand(null);
              resolve(isCurrent() ? value : 'stale');
            };
            const timeout = setTimeout(() => finish('unknown'), RENDER_TIMEOUT_MS);
            frame.current = { id, seq, renderer: opts.rendererId, finish };
            setState('applying');
            // Full-frame confirmation also supports a removed layer (there is no painted zone).
            setRenderCommand({ kind: 'restore', restoreId: id, commandId: id, rendererId: opts.rendererId,
              renderSeq: seq, makeup: opts.preview ? opts.preview(makeup, strength, modified) : arPaintMakeup(makeup) });
          });
          try {
            outcome = await operation({ ...preference, name: tool.name as string | undefined, value: tool.value as number | undefined,
              previousIntensityChange: previousAdjustmentId && tool.fineAdjustment === true ? prior?.amount : undefined,
              steps: typeof tool.steps === 'number' ? tool.steps : undefined,
              ordinal: typeof tool.ordinal === 'number' ? tool.ordinal : undefined,
              productId: typeof tool.productId === 'string' ? tool.productId : undefined,
              shadeId: typeof tool.shadeId === 'string' ? tool.shadeId : undefined }, confirm);
          } catch { outcome = { status: 'FAILED', reason: 'operation failed' }; }
        }
        if (owned() && outcome.status === 'APPLIED') onPainted?.();
        if (owned()) executed.current.set(id, outcome);
        const intensityChange = confirmedIntensityChange(choice, outcome);
        const version = useMakeupStore.getState().arVersion;
        const remember = !voiceCall && owned() && tool.sessionId === sessionId && intensityChange && version > snapshot.arVersion;
        if (!voiceCall) queueArAck({ requestId, commandId: id, sessionId, actualStateVersion: version,
          status: outcome.status, ...(remember && { intensityChange }) }, owner);
        if (!owned()) return;
        if (outcome.status !== 'OK') lastAdjustment.current = remember
          ? { commandId: id, version, amount: Math.abs(intensityChange.after - intensityChange.before) } : null;
        setControlChoice(choice);
        setControlResult(outcome);
        setState(outcome.status === 'OK' ? 'applied' : outcome.status.toLowerCase() as Phase);
        const prepared = !voiceCall && !signal?.aborted && intensityChange && typeof tool.onAppliedReply === 'string'
          ? tool.onAppliedReply.trim() || undefined : undefined;
        let answer = prepared ?? opts.fallbackText?.(outcome) ?? '';
        setMessage(answer);
        if (voiceCall) {
          activeRequest.current = null;
          busy.current = false;
          return JSON.stringify({ choice, displayMode: opts.control.displayMode, ...outcome });
        }
        if (prepared) {
          activeRequest.current = null;
          busy.current = false;
          return prepared;
        }
        try {
          const feedback = await apiPostOwned<{ answer: string }>('/api/chat/ar-control/reply', {
            requestId, commandId: id, message: text, locale: opts.locale, result: JSON.stringify({ choice,
              displayMode: choice === 'control_camera/swatches_only' && outcome.status === 'APPLIED' ? 'swatches_only' : opts.control.displayMode, ...outcome }),
          }, { expectedOwner: owner, timeoutMs: 15000, signal });
          if (owned() && feedback.data.answer?.trim()) {
            answer = feedback.data.answer;
            setMessage(answer);
          }
        } catch { /* The local result remains visible if narration is unavailable. */ }
        if (owned()) { activeRequest.current = null; busy.current = false; return answer; }
        return;
      }
      const proposal = proposalOf(result.actionProposal);
      if (!proposal) throw new Error('Invalid AR proposal');
      const cmd: Command = { requestId, sessionId, owner, proposal, renderSeq: ++sequence.current, rendererId: opts.rendererId, authEpoch: epoch };
      if (!isCurrent() || !current.current.enabled) {
        complete(cmd, { status: 'REJECTED', actualStateVersion: useMakeupStore.getState().arVersion });
        return;
      }
      const prepared = useMakeupStore.getState().prepareArCommand(requestId, sessionId, proposal);
      if (prepared.status !== 'PENDING') { complete(cmd, prepared); return; }
      command.current = cmd;
      const latest = arPaintMakeup(useMakeupStore.getState().makeup);
      const layer = latest[proposal.zone];
      if (!layer) { command.current = null; complete(cmd, useMakeupStore.getState().cancelArCommand()!); return; }
      const updated = proposal.action === 'set_geometry' ? { ...layer, geometry: { ...layer.geometry, ...proposal.geometry } } : { ...layer, intensity: proposal.value };
      setState('proposed');
      setRenderCommand({ zone: proposal.zone, commandId: proposal.commandId, renderSeq: cmd.renderSeq, rendererId: cmd.rendererId, makeup: { ...latest, [proposal.zone]: updated } });
      setState('applying');
      timer.current = setTimeout(() => {
        if (command.current !== cmd) return;
        command.current = null;
        complete(cmd, useMakeupStore.getState().finishArCommand(proposal.commandId, sessionId, 'unknown'), true);
      }, RENDER_TIMEOUT_MS);
    } catch {
      if (mounted.current && activeRequest.current === requestId) {
        activeRequest.current = null;
        busy.current = false;
        setState(signal?.aborted ? 'rejected' : 'failed');
      }
    }
  }, [complete]);

  return { state, applied, controlChoice, controlResult, message, restoreState, ackPending, send, retryAck: retryArAcks, renderCommand, onRenderResult };
}
