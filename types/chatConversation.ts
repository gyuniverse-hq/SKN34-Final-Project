import type { BeautyChatContext, ChatProductEvidence, ChatProductRef, ChatResponse, ChatScreenContext, ChatStyleContext } from './index';

export type ConversationSubject =
  | { type: 'general' }
  | { type: 'look'; kind: ChatStyleContext['kind']; lookId: string }
  | { type: 'product'; productId: string };

export type ConversationEntry =
  | Extract<ConversationSubject, { type: 'general' | 'look' }>
  | (Extract<ConversationSubject, { type: 'product' }> & { shadeId?: string });

export type ChatCategory = 'product' | 'ingredient' | 'style';
export type ChatMessage = {
  id: string;
  role: 'user' | 'assistant';
  automatic?: boolean;
  resultSetId?: string;
  text: string;
  products?: ChatProductRef[];
  question?: string;
  category?: ChatCategory;
  failed?: boolean;
  chatContext?: BeautyChatContext;
  evidence?: ChatProductEvidence[];
  resultType?: ChatResponse['resultType'];
  ingredientResults?: ChatResponse['ingredientResults'];
  ingredientComparison?: ChatResponse['ingredientComparison'];
  fragranceSearchSummary?: ChatResponse['fragranceSearchSummary'];
  screenContext?: ChatScreenContext;
  locale?: 'ko' | 'en' | 'ja' | 'zh';
  errorKey?: string;
  selectionRevision?: number;
  generation?: number;
  ownerKey?: string;
  sessionStatus?: ChatResponse['sessionStatus'];
  retryable?: boolean;
  styleRecipe?: ChatResponse['styleRecipe'];
};

export type ChatRequestSnapshot = {
  args: {
    message: string;
    locale: NonNullable<ChatMessage['locale']>;
    category: ChatCategory;
    requestId: string;
    expectedUserId: string | null;
    chatContext?: BeautyChatContext;
    screenContext?: ChatScreenContext;
    styleContext?: ChatStyleContext;
  };
  automatic: boolean;
  generalMakeup?: boolean;
  revision: number;
  generation: number;
  styleRevision: number;
};

// The owner key includes the authentication epoch, even when the same user logs in again.
export type ConversationTarget = { id: string; ownerKey: string };
export type ChatRequestTicket = ConversationTarget & {
  messageId: string;
  requestId: string;
  generation: number;
  attempt: number;
};
