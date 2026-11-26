import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useFocusEffect } from 'expo-router';
import { useCallback } from 'react';
import { AppState } from 'react-native';
import { apiGet, apiPost } from '@/lib/api';
import type { RewardWallet } from '@/types';

export const rewardsKey = (owner?: string) => ['reward-wallet', owner] as const;

export function useRewards(owner?: string) {
  const client = useQueryClient();
  const query = useQuery({
    queryKey: rewardsKey(owner),
    queryFn: () => apiGet<RewardWallet>('/api/me/rewards', { expectedUserId: owner }),
    enabled: !!owner,
    retry: 1,
    refetchInterval: ({ state }) => state.data && state.status === 'success'
      ? Math.max(1000, Date.parse(state.data.refreshAt) - Date.now() + 100) : false,
  });
  const { refetch } = query;
  useFocusEffect(useCallback(() => {
    if (!owner) return;
    void refetch({ cancelRefetch: false });
    const listener = AppState.addEventListener('change', state => {
      if (state === 'active') void refetch({ cancelRefetch: false });
    });
    return () => listener.remove();
  }, [owner, refetch]));
  const attend = async () => {
    if (!owner) return;
    const wallet = await apiPost<RewardWallet>('/api/me/rewards/attendance', {}, { expectedUserId: owner });
    await client.cancelQueries({ queryKey: rewardsKey(owner) });
    client.setQueryData(rewardsKey(owner), wallet);
  };
  return { ...query, attend };
}
