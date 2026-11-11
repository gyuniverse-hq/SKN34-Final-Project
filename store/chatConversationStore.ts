import { uuid } from 'expo';
import { create } from 'zustand';
import type { TranslationKey } from '@/lib/i18n';
import type { BeautyChatContext, ChatScreenContext, ChatStyleContext } from '@/types';
import type { ChatCategory, ChatMessage, ChatRequestSnapshot, ConversationEntry, ConversationSubject } from '@/types/chatConversation';

function subjectKey(subject: ConversationSubject) {
  if (subject.type === 'look') return `look:${subject.kind}:${subject.lookId}`;
  if (subject.type === 'product') return `product:${subject.productId}`;
  return 'general';
}

export function isChatSessionExpired(expiresAt: number) {
  return expiresAt * 1000 <= Date.now();
}

function screenForEntry(entry: ConversationEntry): ChatScreenContext | undefined {
  if (entry.type !== 'product') return;
  return { screenId: 'product-detail', productId: entry.productId, ...(entry.shadeId ? { shadeId: entry.shadeId } : {}) };
}

function createChatConversation(userId: string | null, ownerKey: string, entry: ConversationEntry, fresh: boolean, focus?: { product?: ChatScreenContext; style?: ChatStyleContext }) {
  const subject: ConversationSubject = entry.type === 'product' ? { type: 'product', productId: entry.productId } : entry;
  return {
    id: uuid.v4(),
    subject,
    userId,
    draft: { current: '' },
    notice: { current: undefined as TranslationKey | undefined },
    request: { current: undefined as string | undefined },
    bootstrap: { current: (fresh ? 'skipped' : 'not-started') as 'skipped' | 'not-started' | 'pending' | 'ready' | 'failed' },
    ownerKey,
    serial: { current: 0 },
    generation: { current: 0 },
    beautyContext: { current: undefined as BeautyChatContext | undefined },
    beautyContextTurn: { current: 0 },
    selection: { current: {
      revision: 0, shades: {} as Record<string, string>, changed: {} as Record<string, number>,
      screen: undefined as ChatScreenContext | undefined,
    } },
    styleContext: { current: (entry.type === 'look' ? { kind: entry.kind, lookId: entry.lookId, currentStep: 0 } : focus?.style ? { kind: focus.style.kind, lookId: focus.style.lookId, currentStep: 0 } : undefined) as ChatStyleContext | undefined },
    styleRevision: { current: 0 },
    entryProduct: { current: screenForEntry(entry) ?? focus?.product },
    snapshots: { current: new Map<string, ChatRequestSnapshot>() },
    category: { current: (entry.type === 'look' || focus?.style ? 'style' : 'product') as ChatCategory },
  };
}

export type ChatConversationState = ReturnType<typeof createChatConversation>;

function readConversationView(owner: ChatConversationState) {
  const context = owner.beautyContext.current;
  return {
    category: owner.category.current,
    pending: !!owner.request.current,
    draft: owner.draft.current,
    notice: owner.notice.current,
    sessionExpiry: context?.session?.expiresAt,
    resultSetId: context?.session?.resultSetId,
    activeStyle: owner.styleContext.current,
    linkedProduct: owner.selection.current.screen ?? owner.entryProduct.current,
    generation: owner.generation.current,
    selectedShades: owner.selection.current.shades,
    chosenProductId: context?.selectedProductId ?? null,
    sessionCandidateIds: context?.session ? context.candidateIds : [],
  };
}

export type ConversationRecord = {
  conversation: ChatConversationState;
  messages: ChatMessage[];
  view: ReturnType<typeof readConversationView>;
  updatedAt: number;
};

type ChatStore = {
  identity?: { userId: string | null; key: string };
  conversations: Record<string, ConversationRecord>;
  latest: Record<string, string>;
  activate: (userId: string | null) => void;
  open: (entry: ConversationEntry, fresh?: boolean, focus?: { product?: ChatScreenContext; style?: ChatStyleContext }) => string | undefined;
  resume: (id: string) => boolean;
  update: (conversation: ChatConversationState, messages?: (items: ChatMessage[]) => ChatMessage[]) => void;
};

let ownerGeneration = 0;
export const useChatConversationStore = create<ChatStore>((set, get) => ({
  conversations: {},
  latest: {},
  activate: (userId) => set((state) => state.identity?.userId === userId ? state : {
    identity: { userId, key: `${userId ?? 'guest'}:${++ownerGeneration}` },
    conversations: {},
    latest: {},
  }),
  open: (entry, fresh = false, focus) => {
    const { identity, latest, conversations } = get();
    if (!identity) return;
    const key = subjectKey(entry);
    const existing = !fresh ? conversations[latest[key]] : undefined;
    if (existing) {
      const room = existing.conversation;
      const screen = screenForEntry(entry);
      if (entry.type === 'product' && screen &&
        (room.selection.current.screen || room.entryProduct.current?.shadeId !== screen.shadeId)) {
        room.entryProduct.current = screen;
        const selection = room.selection.current;
        selection.revision += 1;
        selection.screen = undefined;
        selection.changed[entry.productId] = selection.revision;
        const shades = { ...selection.shades };
        if (entry.shadeId) shades[entry.productId] = entry.shadeId;
        else delete shades[entry.productId];
        selection.shades = shades;
        get().update(room);
      }
      return room.id;
    }
    const conversation = createChatConversation(identity.userId, identity.key, entry, fresh, focus);
    set({
      latest: { ...latest, [key]: conversation.id },
      conversations: { ...conversations, [conversation.id]: {
        conversation, messages: [], view: readConversationView(conversation), updatedAt: Date.now(),
      } },
    });
    return conversation.id;
  },
  resume: (id) => {
    const { conversations, latest } = get();
    const record = Object.hasOwn(conversations, id) ? conversations[id] : undefined;
    if (!record) return false;
    set({ latest: { ...latest, [subjectKey(record.conversation.subject)]: id } });
    return true;
  },
  update: (conversation, messages) => set((state) => {
    const record = state.conversations[conversation.id];
    if (record?.conversation !== conversation) return state;
    return { conversations: { ...state.conversations, [conversation.id]: {
      conversation,
      messages: messages ? messages(record.messages) : record.messages,
      view: readConversationView(conversation),
      updatedAt: messages ? Date.now() : record.updatedAt,
    } } };
  }),
}));
