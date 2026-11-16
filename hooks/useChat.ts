import { useMutation } from '@tanstack/react-query';
import { uuid } from 'expo';
import { apiPostChat } from '@/lib/api';
import type { RecentChatMessage, BeautyChatContext, ChatResponse, ChatScreenContext, ChatStyleContext } from '@/types';

type ChatLocale = 'en' | 'ko' | 'ja' | 'zh';
const CHAT_TIMEOUT_MS = 90_000;

export function useChat() {
  return useMutation({
    retry: false,
    mutationFn: async ({ message, locale, category, chatContext, screenContext, styleContext, requestId, expectedUserId, generalMakeup, recentMessages, clarificationId }: {
      message: string; locale: ChatLocale; category?: 'product' | 'ingredient' | 'style';
      chatContext?: BeautyChatContext;
      screenContext?: ChatScreenContext;
      styleContext?: ChatStyleContext;
      requestId?: string;
      expectedUserId?: string | null;
      generalMakeup?: boolean;
      recentMessages?: RecentChatMessage[];
      clarificationId?: string;
    }) =>
      apiPostChat<ChatResponse>(
        {
          ...(recentMessages?.length ? { recentMessages } : {}),
          ...(clarificationId ? { clarificationId } : {}),
          message, locale, requestId: requestId ?? uuid.v4(),
          ...(generalMakeup ? { generalMakeup: true } : {}),
          ...(category || (!generalMakeup && chatContext) || screenContext || styleContext
            ? { requestType: category === 'style' && !chatContext ? 'style_consultation' : 'beauty_consultation' }
            : {}),
          ...(styleContext ? { styleContext } : {}),
          ...(chatContext ? { chatContext } : {}),
          ...(screenContext ? { screenContext } : {}),
        },
        {
          timeoutMs: CHAT_TIMEOUT_MS,
          expectedUserId,
        }
      ),
  });
}
