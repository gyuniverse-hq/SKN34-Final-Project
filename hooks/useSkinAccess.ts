import AsyncStorage from '@react-native-async-storage/async-storage';
import { useQuery } from '@tanstack/react-query';
import { apiGet } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { readSkinProfile } from '@/lib/skinProfile';
import { recoverMemberReport } from '@/lib/skinRegistration';
import { STORAGE_KEYS } from '@/lib/storage';

export interface SkinAccess { subscribed: boolean; trialUsed: boolean; expiresAt: string | null }
export const skinAccessKey = (owner: string | null) => ['skin-access', owner] as const;

export function useSkinAccess() {
  const { user, ready } = useAuth();
  const owner = user?.id ?? null;
  const query = useQuery({
    queryKey: skinAccessKey(owner),
    queryFn: async (): Promise<SkinAccess> => {
      if (owner) {
        await recoverMemberReport(owner);
        return apiGet('/api/me/skin-access', { expectedUserId: owner });
      }
      const used = await AsyncStorage.getItem(STORAGE_KEYS.guestSkinTrial);
      return { subscribed: false, expiresAt: null, trialUsed: Boolean(used || await readSkinProfile()) };
    },
    enabled: ready,
    staleTime: 0,
    refetchInterval: state => {
      const data = state.state.data;
      if (!data?.subscribed || !data.expiresAt) return false;
      return Math.min(2_147_000_000, Math.max(1000, Date.parse(data.expiresAt) - Date.now() + 100));
    },
    retry: 1,
  });
  const subscribed = ready && query.isSuccess && query.data.subscribed && !!query.data.expiresAt
    && Date.parse(query.data.expiresAt) > Date.now();
  return { owner, ready: ready && query.isSuccess, subscribed,
    trialUsed: query.data?.trialUsed === true, error: query.isError, retry: query.refetch };
}
