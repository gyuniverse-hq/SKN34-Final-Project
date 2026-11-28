import { createMakeupStore, useMakeupStore } from '@/store/makeupStore';
import type { MakeupState, MakeupZone } from '@/types';
import type { ColorFamily } from './colorFamily';
import type { ShadePreference } from './arShadePreference';
import type { catalogMatches } from './arMakeupControls';

export type ControlStatus = 'OK' | 'APPLIED' | 'NO_CHANGE' | 'REJECTED' | 'FAILED' | 'UNKNOWN';
export interface ControlResult {
  status: ControlStatus;
  data?: unknown;
  reason?: string;
  before?: unknown;
  after?: unknown;
  renderPending?: true;
  featuredShade?: { brand:string; product:string; productKo:string; shade:string; shadeNumber?:string; family?:ColorFamily;
    lightness?: ShadePreference['lightness']; chroma?: ShadePreference['chroma'] };
}
export interface ControlArgs extends ShadePreference { name?: string | null; value?: number | null; steps?: number; ordinal?: number; productId?: string; shadeId?: string; previousIntensityChange?: number }
export type ConfirmPaint = (makeup: MakeupState, strength?: number, modified?: MakeupZone[]) => Promise<'rendered' | 'failed' | 'unknown' | 'stale'>;
export type ControlOperation = (args: ControlArgs, confirm: ConfirmPaint) => ControlResult | Promise<ControlResult>;
export interface ControlScreen {
  matchCatalog?: (message: string) => ReturnType<typeof catalogMatches>;
  summary: string;
  choices: Map<string, ControlOperation>;
  displayMode: 'face' | 'swatches_only' | 'unavailable';
  contextKey: string;
  catalogApplyKey: string;
}
export const result = (status: ControlStatus, data?: unknown): ControlResult => ({ status, data });
export const reject = (reason: string): ControlResult => ({ status: 'REJECTED', reason });
type Store = ReturnType<typeof useMakeupStore.getState>;

/** Run the same manual control on an isolated state. Commit only after the frame is confirmed. */
export async function paintControl(edit: (s: Store) => void, confirm: ConfirmPaint, swatches: boolean,
  describe: (s: Store) => unknown, store = useMakeupStore): Promise<ControlResult> {
  const source = store.getState();
  if (source.fit) return reject('product locked');
  const draft = createMakeupStore();
  const { makeup, selections, careSelection, colorLinks, activeLook, modified, lookOrigin } = source;
  draft.setState({ makeup, selections, careSelection, colorLinks, activeLook, modified, lookOrigin });
  edit(draft.getState());
  const next = draft.getState();
  const before = describe(source);
  const after = describe(next);
  if (JSON.stringify([makeup, selections, careSelection]) ===
      JSON.stringify([next.makeup, next.selections, next.careSelection])) {
    return { status: 'NO_CHANGE', before, after };
  }
  const frame = swatches ? 'rendered' : await confirm(next.makeup, undefined, next.modified);
  if (frame === 'stale' || source.arVersion !== store.getState().arVersion) return reject('state changed');
  if (frame !== 'rendered') return { status: frame === 'failed' ? 'FAILED' : 'UNKNOWN', reason: 'render ' + frame };
  edit(store.getState());
  return { status: 'APPLIED', before, after };
}

export function adjacentIndex(index: number, steps: number, count: number) {
  if (!count) return -1;
  return count > 7 ? ((index + steps) % count + count) % count : Math.max(0, Math.min(count - 1, index + steps));
}

export function intensityTarget(current: number, mode: string, min: number, value?: number | null, previousIntensityChange?: number) {
  if (mode === 'absolute') return typeof value === 'number' && Number.isFinite(value) && value >= min && value <= 1 ? value : null;
  // Round half of the confirmed change to the nearest 0.01, with a one-step minimum.
  const step = previousIntensityChange === undefined ? 0.1
    : Math.max(1, Math.round((previousIntensityChange + Number.EPSILON) * 0.5 * 100)) / 100;
  const scaled = mode === 'up' ? current + step : mode === 'down' ? current - step : current / 2;
  return Math.min(1, Math.max(min, Math.round(scaled * 1000) / 1000));
}
