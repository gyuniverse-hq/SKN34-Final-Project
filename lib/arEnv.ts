/**
 * AR shooting-environment guidance (11-19). The AR page (components/ar/faceTrackerHtml.ts envEvaluate) measures the scene
 * and sends one settled state `{ type: 'env', primary, level, items, ready }`; this module parses it and decides which one
 * message the AR screen shows, for how long, and when not to repeat it. Correction never depends on these messages.
 */
import type { TranslationKey } from '@/lib/i18n';

export const ENV_IDS = [
  'position', 'blown', 'backlight', 'dark', 'motion', 'turn', 'tooClose', 'tooFar', 'unevenLight', 'warmLight', 'colorCast',
  'lightChanged', 'estimating',
] as const;
export type EnvId = (typeof ENV_IDS)[number];
export type EnvLevel = 'ok' | 'degraded' | 'ask';
/** Message keys shown on screen: the page conditions plus the start-up "good" note and the no-face note. */
export type EnvMessageId = EnvId | 'normal' | 'noFace';

/** i18n key of each on-screen message (all four dictionaries carry them). */
export const ENV_MESSAGE_KEY: Record<EnvMessageId, TranslationKey> = {
  normal: 'ar.env.normal', noFace: 'ar.env.noFace', position: 'ar.env.position', blown: 'ar.env.blown',
  backlight: 'ar.env.backlight', dark: 'ar.env.dark', motion: 'ar.env.motion', turn: 'ar.env.turn', tooClose: 'ar.env.tooClose',
  tooFar: 'ar.env.tooFar', unevenLight: 'ar.env.unevenLight', warmLight: 'ar.env.warmLight', colorCast: 'ar.env.colorCast',
  lightChanged: 'ar.env.lightChanged', estimating: 'ar.env.estimating',
};

export interface EnvState {
  primary: EnvId | null;
  level: EnvLevel;
  items: EnvId[];
  /** True once the page finished its start-up check (first few scene samples after tracking began). */
  ready: boolean;
}

const isEnvId = (v: unknown): v is EnvId => typeof v === 'string' && (ENV_IDS as readonly string[]).includes(v);

export function parseEnvMessage(message: { primary?: unknown; level?: unknown; items?: unknown; ready?: unknown }): EnvState | null {
  const primary = message.primary == null ? null : isEnvId(message.primary) ? message.primary : undefined;
  if (primary === undefined) return null;
  const level: EnvLevel = message.level === 'ask' || message.level === 'degraded' ? message.level : 'ok';
  const items = Array.isArray(message.items) ? message.items.filter(isEnvId) : [];
  return { primary, level, items, ready: message.ready === true };
}

/** Display rules (TUNING-like, kept here so the screen and the tests share them). */
export const ENV_DISPLAY = {
  minShowMs: 3000,      // a message stays at least this long once shown
  repeatGapMs: 10000,   // the same message is not shown again within this time after it was hidden
  normalShowMs: 3000,   // the start-up "good" note, once per session
};

/**
 * Conditions the page still measures (HUD, logs, `items`) but the screen does not voice. 11-19 decision 4: the left /
 * right split did not tell side light from normal photos (docs/AR_ENV_THRESHOLDS.md), so its message waits for the
 * redesign and a phone check. Correction never depended on it.
 */
export const ENV_MUTED: ReadonlySet<EnvId> = new Set<EnvId>(['unevenLight']);

/** The condition to voice: the page's primary, or the next active one in the page's priority order if that is muted. */
export function voicedEnvId(env: EnvState | null): EnvId | null {
  if (!env) return null;
  if (env.primary && !ENV_MUTED.has(env.primary)) return env.primary;
  return env.items.find((id) => !ENV_MUTED.has(id)) ?? null;
}

/** Rank used to let a more serious message replace the one on screen before its minimum time (lower = more serious). */
const RANK: Record<EnvMessageId, number> = {
  noFace: 0, position: 0, tooClose: 0, blown: 1, backlight: 1, dark: 1, motion: 2, turn: 3, tooFar: 3, unevenLight: 4,
  warmLight: 5, colorCast: 5, lightChanged: 6, estimating: 7, normal: 8,
};

export interface EnvDisplay {
  shown: EnvMessageId | null;
  shownAt: number;
  /** When each message was last hidden (for the repeat gap). */
  hiddenAt: Partial<Record<EnvMessageId, number>>;
  normalDone: boolean;
}

export const initialEnvDisplay = (): EnvDisplay => ({ shown: null, shownAt: 0, hiddenAt: {}, normalDone: false });

/**
 * One step of the display rules. `want` is what the current state asks for (null = nothing), `noFace` comes from the
 * page status. Returns the next display; call it on every env message / status change and on a timer tick.
 */
export function stepEnvDisplay(d: EnvDisplay, env: EnvState | null, noFace: boolean, now: number): EnvDisplay {
  let want: EnvMessageId | null = noFace ? 'noFace' : voicedEnvId(env);
  let normalDone = d.normalDone;
  // Start-up check: a settled state with nothing wrong shows the "good" note once per session.
  if (!want && !noFace && env?.ready && !d.normalDone) {
    want = 'normal';
    normalDone = true;
  }
  const hide = (): EnvDisplay => ({ ...d, normalDone, shown: null, shownAt: 0, hiddenAt: d.shown ? { ...d.hiddenAt, [d.shown]: now } : d.hiddenAt });
  const show = (id: EnvMessageId): EnvDisplay => {
    const base = d.shown && d.shown !== id ? { ...d.hiddenAt, [d.shown]: now } : d.hiddenAt;
    return { shown: id, shownAt: now, hiddenAt: base, normalDone };
  };
  const minLeft = d.shown ? d.shownAt + (d.shown === 'normal' ? ENV_DISPLAY.normalShowMs : ENV_DISPLAY.minShowMs) - now : 0;
  if (d.shown === 'normal' && want === 'normal') return minLeft > 0 ? { ...d, normalDone } : hide();
  if (want === d.shown) return { ...d, normalDone };
  // The normal note is never asked twice: once its time is up it goes.
  if (want === 'normal' && d.shown) return { ...d, normalDone };
  if (want) {
    const gapOk = !(want in d.hiddenAt) || now - (d.hiddenAt[want] ?? 0) >= ENV_DISPLAY.repeatGapMs || want === 'noFace';
    if (!gapOk) return minLeft > 0 ? { ...d, normalDone } : d.shown ? hide() : { ...d, normalDone };
    if (!d.shown || minLeft <= 0 || RANK[want] < RANK[d.shown]) return show(want);
    return { ...d, normalDone };
  }
  // Nothing wanted: keep the current message until its minimum time is up (noFace hides at once).
  if (d.shown && d.shown !== 'noFace' && minLeft > 0) return { ...d, normalDone };
  return d.shown ? hide() : { ...d, normalDone };
}
