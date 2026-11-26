import { useCallback, useEffect, useState } from 'react';
import { useAuth } from '@/lib/auth';
import { useSkinProfileStore } from '@/store/skinProfileStore';

export function useOwnedSkinProfile() {
  const { ready, user } = useAuth();
  const owner = user?.id ?? null;
  const hydrate = useSkinProfileStore(s => s.hydrate);
  const profile = useSkinProfileStore(s => ready && s.owner === owner ? s.profile : null);
  const [loaded, setLoaded] = useState<{ owner: string | null; failed: boolean }>();
  const [attempt, setAttempt] = useState(0);
  const reload = useCallback(() => { setLoaded(undefined); setAttempt(n => n + 1); }, []);
  useEffect(() => {
    if (!ready) return;
    let active = true;
    void hydrate(owner).then(() => {
      if (active) setLoaded({ owner, failed: false });
    }, () => {
      if (active) setLoaded({ owner, failed: true });
    });
    return () => { active = false; };
  }, [ready, owner, hydrate, attempt]);
  return { profile, loading: !ready || loaded?.owner !== owner, loadFailed: loaded?.owner === owner && loaded.failed, reload };
}
