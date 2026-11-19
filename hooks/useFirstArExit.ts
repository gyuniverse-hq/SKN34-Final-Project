import AsyncStorage from '@react-native-async-storage/async-storage';
import { useFocusEffect, useRouter } from 'expo-router';
import { useCallback, useRef } from 'react';
import { apiPost } from '@/lib/api';
import { getCurrentUserId } from '@/lib/auth';
import { readSkinProfile } from '@/lib/skinProfile';
import { offerAction } from '@/lib/confirm';
import { useI18n } from '@/lib/i18n';
import { skinAnalysisSupported } from '@/lib/skinAnalysis';
import { STORAGE_KEYS } from '@/lib/storage';

async function firstVisit() {
  const owner = await getCurrentUserId();
  const marker = owner ? `${STORAGE_KEYS.firstArInvitation}:${owner}` : STORAGE_KEYS.firstArInvitation;
  if (await AsyncStorage.getItem(marker)) return null;
  await AsyncStorage.setItem(marker, '1');
  const eligible = owner
    ? await apiPost<boolean>('/api/me/skin-access/first-ar-visit', {}, { expectedUserId: owner, timeoutMs: 2500 })
    : !await AsyncStorage.getItem(STORAGE_KEYS.guestSkinTrial);
  return eligible && !await readSkinProfile(owner) ? { owner } : null;
}

export function useFirstArExit() {
  const { t } = useI18n();
  const router = useRouter();
  const pending = useRef(false);
  const visit = useRef<ReturnType<typeof firstVisit> | null>(null);
  useFocusEffect(useCallback(() => {
    if (skinAnalysisSupported) visit.current = firstVisit().catch(() => null);
    return () => { visit.current = null; };
  }, []));
  return useCallback(async (leave: () => void) => {
    if (pending.current) return;
    if (!skinAnalysisSupported) { leave(); return; }
    pending.current = true;
    const finish = (action: () => void) => { pending.current = false; action(); };
    try {
      const current = visit.current;
      const eligible = await current;
      if (visit.current !== current) { pending.current = false; return; }
      if (!eligible || await getCurrentUserId() !== eligible.owner) { finish(leave); return; }
      visit.current = null;
      offerAction(t('skinAccess.arInvite'), t('skinAccess.analyze'), t('skinAccess.later'),
        () => finish(() => router.replace('/skin-consent')), () => finish(leave));
    } catch { finish(leave); }
  }, [router, t]);
}
