import { uuid } from 'expo';
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { apiPostOwned, subscribeArIdentityChange, type ArRequestOwner } from '@/lib/api';
import { pendingArAcks, queueArAck, retryArAcks, subscribeArAcks } from '@/lib/arCommandAck';
import { revealedMakeup } from '@/lib/practice';
import type { Language } from '@/lib/i18n';
import { geometryFromStyle } from '@/lib/zoneRecipe';
import { AR_PAINT_ZONES, arPaintMakeup, isArPaintZone, isLookPaintZone, useMakeupStore, type ArOutcome, type ArProposal } from '@/store/makeupStore';
import type { ArRenderCommand, ArRenderResult, MakeupZone, ZoneGeometry } from '@/types';

type Phase = 'idle' | 'interpreting' | 'proposed' | 'applying' | 'applied' | 'no_change' | 'clarification' | 'rejected' | 'failed' | 'unknown';
type RestorePhase = 'idle' | 'pending' | 'confirmed' | 'failed' | 'unknown' | 'unavailable';
type Command = { requestId: string; sessionId: string; owner: ArRequestOwner; proposal: ArProposal; renderSeq: number; rendererId: string; authEpoch: number };
type Restore = { cmd: Command; restoreId: string; renderSeq: number; rendererId: string; stateVersion: number; displayKey: string };
type Options = { active: boolean; enabled: boolean; activeZone: MakeupZone; locale: Language; rendererId: string; visibleZones?: MakeupZone[] | null };
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const RENDER_TIMEOUT_MS = 6000;
const displayKey = (options: Options) => options.visibleZones ? options.visibleZones.join('|') : '*';

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
  const command = useRef<Command | null>(null);
  const sequence = useRef(0);
  const busy = useRef(false);
  const activeRequest = useRef<string | null>(null);
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
    useMakeupStore.setState({ arUndo: null });
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
    useMakeupStore.getState().beginArSession(id);
    const unsubscribe = useMakeupStore.subscribe((next, previous) => {
      const restoring = restore.current;
      const pending = previous.pendingArCommand;
      if (pending && !next.pendingArCommand && command.current?.proposal.commandId === pending.proposal.commandId) {
        complete(command.current, { status: 'REJECTED', actualStateVersion: next.arVersion }, true);
      }
      if (!previous.pendingArCommand && !next.pendingArCommand && activeRequest.current && !command.current &&
          requestVersion.current !== next.arVersion) {
        activeRequest.current = null;
        busy.current = false;
        if (mounted.current) { setState('idle'); setMessage(''); }
      }
      if (restoring && restore.current === restoring && next.arVersion !== previous.arVersion) startRestore(restoring.cmd);
    });
    return () => {
      session.current = null;
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
    if (activeRequest.current && (!options.active || !options.enabled || requestRendererId.current !== options.rendererId)) {
      activeRequest.current = null;
      busy.current = false;
      if (mounted.current) setState('idle');
    }
  }, [options.active, options.enabled, options.rendererId]);

  useLayoutEffect(() => {
    const pending = restore.current;
    if (pending && pending.displayKey !== displayKey(options)) startRestore(pending.cmd);
  }, [options, startRestore]);

  const onRenderResult = useCallback((result: ArRenderResult) => {
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

  const send = useCallback(async (text: string) => {
    const opts = current.current;
    const sessionId = session.current;
    if (!text.trim() || busy.current || restore.current || !opts.enabled || !sessionId) return;
    busy.current = true;
    setMessage('');
    setState('interpreting');
    const requestId = uuid.v4();
    activeRequest.current = requestId;
    requestRendererId.current = opts.rendererId;
    const snapshot = useMakeupStore.getState();
    const epoch = authEpoch.current;
    requestVersion.current = snapshot.arVersion;
    const isCurrent = () => authEpoch.current === epoch && activeRequest.current === requestId && session.current === sessionId &&
      mounted.current && current.current.active && current.current.enabled && current.current.rendererId === opts.rendererId &&
      useMakeupStore.getState().arVersion === snapshot.arVersion;
    const selections: Partial<Record<MakeupZone, { productId: string; shadeId: string; intensity: number }>> = {};
    for (const zone of AR_PAINT_ZONES) {
      const product = snapshot.selections[zone];
      const layer = snapshot.makeup[zone];
      if (product && layer) selections[zone] = { ...product, intensity: layer.intensity };
    }
    try {
      const { data: response, owner } = await apiPostOwned<{ answer?: unknown; arResult?: unknown }>('/api/chat', {
        message: text.trim(), locale: opts.locale, requestType: 'ar_command', requestId,
        arContext: { screenId: 'A-01', stateVersion: snapshot.arVersion,
          activeZone: isArPaintZone(opts.activeZone) ? opts.activeZone : null,
          supportedActions: ['set_intensity', 'adjust_intensity', 'undo', 'set_geometry'],
          selections, undo: snapshot.arUndo, lip: zoneSnap(snapshot, 'lip'),
          highlighter: zoneSnap(snapshot, 'highlighter'), contour: zoneSnap(snapshot, 'contour'),
          blush: zoneSnap(snapshot, 'blush'), eyeshadow: zoneSnap(snapshot, 'eyeshadow'),
          eyeliner: zoneSnap(snapshot, 'eyeliner'), mascara: zoneSnap(snapshot, 'mascara') },
      }, { timeoutMs: 90_000 });
      const ar = response?.arResult;
      if (!ar || typeof ar !== 'object') throw new Error('Invalid AR response');
      const result = ar as Record<string, unknown>;
      if (result.requestId !== requestId || typeof result.status !== 'string') throw new Error('Invalid AR response');
      if (result.status !== 'proposed') {
        if (!['clarification', 'unsupported', 'noop'].includes(result.status)) throw new Error('Invalid AR response');
        if (!isCurrent()) return;
        activeRequest.current = null;
        busy.current = false;
        setMessage(typeof response.answer === 'string' ? response.answer : '');
        setState('clarification');
        return;
      }
      const proposal = proposalOf(result.actionProposal);
      if (!proposal) throw new Error('Invalid AR proposal');
      const cmd: Command = { requestId, sessionId, owner, proposal, renderSeq: ++sequence.current, rendererId: opts.rendererId, authEpoch: epoch };
      if (!isCurrent()) {
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
      if (isCurrent()) {
        activeRequest.current = null;
        busy.current = false;
        setState('failed');
      }
    }
  }, [complete]);

  return { state, applied, message, restoreState, ackPending, send, retryAck: retryArAcks, renderCommand, onRenderResult };
}
