import { useMutation } from '@tanstack/react-query';
import { apiPost, CHAT_API_BASE_URL } from '@/lib/api';
import { getAnonymousChatId } from '@/lib/chatIdentity';
import type { ChatResponse } from '@/types';

type ChatLocale = 'en' | 'ko' | 'ja' | 'zh';
const CHAT_TIMEOUT_MS = 90_000;

export function useChat() {
  return useMutation({
    mutationFn: async ({ message, locale }: { message: string; locale: ChatLocale }) =>
      apiPost<ChatResponse>(
        '/api/chat',
        { message, locale },
        { baseUrl: CHAT_API_BASE_URL, timeoutMs: CHAT_TIMEOUT_MS, headers: { 'X-Vishue-Anonymous-Id': await getAnonymousChatId() } }
      ),
  });
}
