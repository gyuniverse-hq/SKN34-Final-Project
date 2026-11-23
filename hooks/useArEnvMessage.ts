import { useEffect, useRef, useState } from 'react';
import { initialEnvDisplay, stepEnvDisplay, voicedEnvId, type EnvMessageId, type EnvState } from '@/lib/arEnv';

/**
 * Which environment message the AR screen shows now (one at a time), from the page's settled env state and the tracking
 * status. Applies lib/arEnv display rules: minimum time on screen, no repeat within the gap, the start-up note once.
 */
export function useArEnvMessage(env: EnvState | null, noFace: boolean): EnvMessageId | null {
  const display = useRef(initialEnvDisplay());
  const [shown, setShown] = useState<EnvMessageId | null>(null);

  useEffect(() => {
    let id: ReturnType<typeof setInterval> | null = null;
    const tick = () => {
      display.current = stepEnvDisplay(display.current, env, noFace, Date.now());
      setShown(display.current.shown);
      // The clock runs only while a timed rule can still change what is shown (a message on screen, or one wanted
      // but waiting out a repeat gap); otherwise nothing is scheduled.
      const pending = !!display.current.shown || !!voicedEnvId(env);
      if (!pending && id) { clearInterval(id); id = null; }
      if (pending && !id) id = setInterval(tick, 500);
    };
    tick();
    return () => { if (id) clearInterval(id); };
  }, [env, noFace]);

  return shown;
}
