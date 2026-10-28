import { useMutation } from '@tanstack/react-query';
import { apiPost } from '@/lib/api';
import { getAnonymousChatId } from '@/lib/chatIdentity';
import type { ChatResponse } from '@/types';

type ChatLocale = 'en' | 'ko' | 'ja' | 'zh';

export function useChat() {
  return useMutation({
    mutationFn: async ({ message, locale }: { message: string; locale: ChatLocale }) =>
      apiPost<ChatResponse>(
        '/api/chat',
        { message, locale },
        { headers: { 'X-Vishue-Anonymous-Id': await getAnonymousChatId() } }
      ),
  });
}
