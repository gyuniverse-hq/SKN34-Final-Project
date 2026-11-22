import { useMutation } from '@tanstack/react-query';
import { uuid } from 'expo';
import { apiPostChat } from '@/lib/api';
import type { RecentChatMessage, BeautyChatContext, ChatResponse, ChatScreenContext, ChatStyleCandidate, ChatStyleContext } from '@/types';

type ChatLocale = 'en' | 'ko' | 'ja' | 'zh';
const CHAT_TIMEOUT_MS = 90_000;

export function useChat() {
  return useMutation({
    retry: false,
    mutationFn: async ({ message, locale, category, chatContext, screenContext, styleContext, styleSearch, previousStyleCandidates, previousStyleSelection, requestId, expectedUserId, generalMakeup, recentMessages, clarificationId }: {
      message: string; locale: ChatLocale; category?: 'product' | 'ingredient' | 'style';
      chatContext?: BeautyChatContext;
      screenContext?: ChatScreenContext;
      styleContext?: ChatStyleContext;
      styleSearch?: boolean;
      previousStyleCandidates?: Pick<ChatStyleCandidate, 'kind' | 'lookId'>[];
      previousStyleSelection?: Pick<ChatStyleCandidate, 'kind' | 'lookId'>;
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
          ...(styleSearch ? { styleSearch: true } : {}),
          ...(previousStyleCandidates?.length ? { previousStyleCandidates } : {}),
          ...(previousStyleSelection ? { previousStyleSelection } : {}),
          ...(generalMakeup ? { generalMakeup: true } : {}),
          ...(category || (!generalMakeup && chatContext) || screenContext || styleContext || styleSearch
            ? { requestType: styleSearch || (category === 'style' && !chatContext) ? 'style_consultation' : 'beauty_consultation' }
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
