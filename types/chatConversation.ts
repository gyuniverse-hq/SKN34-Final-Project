import type { RecentChatMessage, BeautyChatContext, ChatProductEvidence, ChatProductRef, ChatResponse, ChatScreenContext, ChatStyleContext, ChatStyleCondition } from './index';

export type ConversationSubject =
  | { type: 'general' }
  | { type: 'look'; kind: ChatStyleContext['kind']; lookId: string }
  | { type: 'product'; productId: string };

export type ConversationEntry =
  | Extract<ConversationSubject, { type: 'general' | 'look' }>
  | (Extract<ConversationSubject, { type: 'product' }> & { shadeId?: string });

export type ConversationListSummary = {
  titleTopic?: 'product' | 'ingredient' | 'look';
  previewTopics: ('hydration' | 'price')[];
};

export type ServerConversationSummary = {
  conversationId: string;
  conversationVersion: number;
  subject: ConversationEntry;
  updatedAt: string;
  listSummary?: ConversationListSummary;
};

export type ServerConversationDetail = Omit<ServerConversationSummary, 'updatedAt' | 'listSummary'> & {
  updatedAt?: string;
  context: {
    product?: {
      selectedProductId?: string | null;
      selectedShadeId?: string | null;
      historicalCandidateRefs?: string[];
      filters?: Pick<BeautyChatContext['filters'], 'optionSearch'>;
    } | null;
    style?: (ChatStyleContext & { conditions?: ChatStyleCondition[] }) | null;
    styleConditions?: ChatStyleCondition[];
  };
  messages: { id: string; role: 'user' | 'assistant'; text: string; displayPayload?: Partial<ChatResponse> | null; createdAt: string }[];
  nextMessageCursor?: number | null;
};

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
  optionSearch?: ChatResponse['optionSearch'];
  compound?: ChatResponse['compound'];
  ingredientResults?: ChatResponse['ingredientResults'];
  knowledge?: ChatResponse['knowledge'];
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
  styleCandidates?: ChatResponse['styleCandidates'];
  styleStatus?: ChatResponse['styleStatus'];
  memoryProposal?: ChatResponse['memoryProposal'];
  appliedMemories?: ChatResponse['appliedMemories'];
};

export type ChatRequestSnapshot = {
  args: {
    recentMessages?: RecentChatMessage[];
    clarificationId?: string;
    generalMakeup?: boolean;
    message: string;
    locale: NonNullable<ChatMessage['locale']>;
    category?: ChatCategory;
    requestId: string;
    expectedUserId: string | null;
    chatContext?: BeautyChatContext;
    screenContext?: ChatScreenContext;
    styleContext?: ChatStyleContext;
    styleSearch?: boolean;
    excludedStyle?: Pick<NonNullable<ChatResponse['styleCandidates']>[number], 'kind' | 'lookId'>;
    previousStyleCandidates?: Pick<NonNullable<ChatResponse['styleCandidates']>[number], 'kind' | 'lookId'>[];
    previousStyleSelection?: Pick<NonNullable<ChatResponse['styleCandidates']>[number], 'kind' | 'lookId'>;
    styleConditions?: ChatStyleCondition[];
    styleCompare?: boolean;
  };
  automatic: boolean;
  generalMakeup?: boolean;
  revision: number;
  generation: number;
  styleRevision: number;
  statePatchId?: string;
  serverBaseVersion?: number;
};

// The owner key includes the authentication epoch, even when the same user logs in again.
export type ConversationTarget = { id: string; ownerKey: string };
export type ChatRequestTicket = ConversationTarget & {
  messageId: string;
  requestId: string;
  generation: number;
  attempt: number;
};
