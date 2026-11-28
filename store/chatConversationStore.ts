import { uuid } from 'expo';
import { create } from 'zustand';
import type { TranslationKey } from '@/lib/i18n';
import type { PendingClarification, RecentChatMessage, BeautyChatContext, ChatMemorySettings, ChatResponse, ChatScreenContext, ChatStyleContext, ChatStyleCondition } from '@/types';
import type { ChatCategory, ChatMessage, ConversationTarget, ChatRequestTicket, ChatRequestSnapshot, ConversationEntry, ConversationListSummary, ConversationSubject, ServerConversationSummary, ServerConversationDetail } from '@/types/chatConversation';

// Select complete pairs from this room; Unicode code points match Python len().
export function recentChatMessages(messages: ChatMessage[], ownerKey: string, generation: number): RecentChatMessage[] {
  const result: RecentChatMessage[] = [];
  let total = 0;
  for (let i = messages.length - 1; i > 0; i -= 1) {
    const answer = messages[i], question = messages[i - 1];
    if (answer.role !== 'assistant' || question.role !== 'user') continue;
    if ([question, answer].some((m) => m.failed || m.automatic || m.ownerKey !== ownerKey || m.generation !== generation)) continue;
    const q = Array.from(question.text).length, a = Array.from(answer.text).length;
    // Stop at a gap rather than silently use older context in place of the latest turn.
    if (!q || !a || q > 1000 || a > 2000 || total + q + a > 8000 || result.length + 2 > 8) break;
    result.unshift({ id: question.id, role: 'user', text: question.text },
      { id: answer.id, role: 'assistant', text: answer.text });
    total += q + a;
    i -= 1;
  }
  return result;
}

export function recentStyleMessages(messages: ChatMessage[], ownerKey: string, generation: number): RecentChatMessage[] {
  const turns = messages.flatMap((answer, index) => {
    const question = messages[index - 1];
    if (answer.role !== 'assistant' || answer.styleCandidates === undefined || question?.role !== 'user' ||
      [answer, question].some((item) => item.failed || item.automatic || item.ownerKey !== ownerKey || item.generation !== generation) ||
      !question.text || Array.from(question.text).length > 1000) return [];
    return [{ id: question.id, role: 'user' as const, text: question.text }];
  });
  const grouped: RecentChatMessage[] = [];
  for (const turn of turns) {
    const last = grouped.at(-1);
    if (last && Array.from(`${last.text}\n${turn.text}`).length <= 1000) last.text += `\n${turn.text}`;
    else grouped.push({ ...turn });
  }
  // shortcut: very long chats keep the first and latest groups; G7 can provide durable context.
  return grouped.length > 8 ? [grouped[0], ...grouped.slice(-7)] : grouped;
}

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
  return { screenId: 'product-detail', productId: entry.productId, ...(entry.shadeId ? { shadeId: entry.shadeId } : {}), ...(entry.optionId ? { optionId: entry.optionId } : {}) };
}

export type RequestRecoveryStatus = 'checking' | 'in_progress' | 'not_found' | 'auth' | 'unconfirmed' | 'interrupted' | 'failed';
type RequestRecovery = { requestId: string; status: RequestRecoveryStatus; messageId?: string };

export function isRequestRecoveryPending(recovery: RequestRecovery | undefined) {
  return !!recovery && recovery.status !== 'interrupted' && recovery.status !== 'failed';
}

function createChatConversation(userId: string | null, ownerKey: string, entry: ConversationEntry, fresh: boolean, focus?: { product?: ChatScreenContext; style?: ChatStyleContext }) {
  const subject: ConversationSubject = entry.type === 'product' ? { type: 'product', productId: entry.productId } : entry;
  return {
    id: uuid.v4(),
    subject,
    userId,
    serverId: undefined as string | undefined,
    serverVersion: 0,
    serverSummary: false,
    olderMessageCursor: undefined as number | undefined,
    persistenceMode: 'unknown' as 'unknown' | 'enabled' | 'disabled',
    deletionState: undefined as 'pending' | 'failed' | undefined,
    draft: '',
    notice: undefined as TranslationKey | undefined,
    request: undefined as string | undefined,
    requestRecovery: undefined as RequestRecovery | undefined,
    bootstrap: (fresh ? 'skipped' : 'not-started') as 'skipped' | 'not-started' | 'pending' | 'ready' | 'failed',
    ownerKey,
    serial: 0,
    attempt: 0,
    generation: 0,
    pendingClarification: undefined as PendingClarification | undefined,
    dismissedClarificationId: undefined as string | undefined,
    beautyContext: undefined as BeautyChatContext | undefined,
    beautyContextTurn: 0,
    selection: {
      revision: 0, shades: {} as Record<string, string>, changed: {} as Record<string, number>,
      screen: undefined as ChatScreenContext | undefined,
    },
    styleContext: (entry.type === 'look' ? { kind: entry.kind, lookId: entry.lookId, currentStep: 0 } : focus?.style ? { kind: focus.style.kind, lookId: focus.style.lookId, currentStep: 0 } : undefined) as ChatStyleContext | undefined,
    styleRevision: 0,
    styleConditions: [] as ChatStyleCondition[],
    entryProduct: screenForEntry(entry) ?? focus?.product,
    snapshots: new Map<string, ChatRequestSnapshot>(),
    category: (entry.type === 'look' || focus?.style ? 'style' : entry.type === 'product' || focus?.product ? 'product' : undefined) as ChatCategory | undefined,
  };
}

export type ChatConversationState = ReturnType<typeof createChatConversation>;

export function canDeleteRoom(room: Readonly<ChatConversationState>) {
  // A lost create response can leave a server room even before its ID is bound.
  return !!room.serverId || !room.userId || room.persistenceMode === 'disabled' || room.attempt === 0;
}

function readConversationView(owner: ChatConversationState) {
  const context = owner.beautyContext;
  return {
    category: owner.category,
    pending: !!owner.request,
    draft: owner.draft,
    notice: owner.notice,
    sessionExpiry: context?.session?.expiresAt,
    resultSetId: context?.session?.resultSetId,
    activeStyle: owner.styleContext,
    linkedProduct: owner.selection.screen ?? owner.entryProduct,
    generation: owner.generation,
    selectedShades: owner.selection.shades,
    chosenProductId: context?.selectedProductId ?? null,
    sessionCandidateIds: context?.session ? context.candidateIds : [],
  };
}

export type ConversationRecord = {
  conversation: Readonly<ChatConversationState>;
  messages: ChatMessage[];
  view: ReturnType<typeof readConversationView>;
  updatedAt: number;
  listSummary?: ConversationListSummary;
  recoveredDeletion?: true;
};

type ChatStore = {
  identity?: { userId: string | null; key: string };
  memoryPolicyVersion?: number;
  conversations: Record<string, ConversationRecord>;
  latest: Record<string, string>;
  removedServerRooms: ReadonlySet<string>;
  activate: (userId: string | null) => void;
  open: (entry: ConversationEntry, fresh?: boolean, focus?: { product?: ChatScreenContext; style?: ChatStyleContext }) => string | undefined;
  resume: (id: string) => boolean;
  mergeServerRooms: (ownerKey: string, rooms: ServerConversationSummary[]) => void;
  restoreServerRoom: (target: ConversationTarget, detail: ServerConversationDetail, generation: number, reload: boolean, committedRequestId?: string) => string | undefined;
  removeMissingServerRoom: (expected: Readonly<ChatConversationState>) => boolean;
  restoreRoomDeletions: (ownerKey: string, serverIds: string[]) => void;
  clearRecoveredRoomDeletions: () => void;
  clearRequestRecoveries: () => void;
  beginRoomDeletion: (target: ConversationTarget) => Readonly<ChatConversationState> | undefined;
  finishRoomDeletion: (expected: Readonly<ChatConversationState>, completed: boolean) => void;
  prependServerMessages: (target: ConversationTarget, cursor: number, detail: ServerConversationDetail) => void;
  setDraft: (target: ConversationTarget, value: string) => void;
  setCategory: (target: ConversationTarget, value: ChatCategory) => void;
  setNotice: (target: ConversationTarget, value: TranslationKey) => void;
  setPersistenceMode: (target: ConversationTarget, value: 'enabled' | 'disabled') => void;
  bindServerRoom: (target: ConversationTarget, id: string, version: number) => void;
  observeMemoryPolicy: (ownerKey: string, settings: Pick<ChatMemorySettings, 'enabled' | 'version'>, force?: boolean) => void;
  invalidateMemoryContext: (ownerKey: string, preserveFirstRequest?: boolean) => void;
  setStyle: (target: ConversationTarget, value?: ChatStyleContext) => void;
  clearProduct: (target: ConversationTarget) => void;
  resetSession: (target: ConversationTarget, key: TranslationKey, keepSelection?: boolean) => void;
  selectProduct: (target: ConversationTarget, productId: string, message: ChatMessage) => void;
  selectShade: (target: ConversationTarget, productId: string, shadeId: string, message: ChatMessage) => void;
  setRecipeStep: (target: ConversationTarget, messageId: string, index: number) => void;
  beginRequest: (target: ConversationTarget, snapshot: ChatRequestSnapshot, retryId?: string) => ChatRequestTicket | undefined;
  beginRequestRecovery: (target: Readonly<ChatConversationState>, requestId: string, ticket?: ChatRequestTicket) => Readonly<ChatConversationState> | undefined;
  finishRequestRecovery: (expected: Readonly<ChatConversationState>, status: RequestRecoveryStatus | 'dismissed') => boolean;
  completeRequest: (ticket: ChatRequestTicket, response: ChatResponse, question: string) => boolean;
  confirmCancellation: (expected: Readonly<ChatConversationState>, version: number) => boolean;
  failRequest: (ticket: ChatRequestTicket, key: TranslationKey, fatal: boolean, ownerError: boolean, clarificationConflict?: boolean) => void;
};

function resetRoom(room: ChatConversationState, record: ConversationRecord, key: TranslationKey, keepSelection = false) {
  room.generation += 1;
  if (room.requestRecovery?.status === 'checking') {
    room.requestRecovery = { ...room.requestRecovery, status: 'unconfirmed' };
  }
  room.beautyContext = undefined;
  room.dismissedClarificationId = undefined;
  room.pendingClarification = undefined;
  room.styleConditions = [];
  room.beautyContextTurn = 0;
  room.snapshots.clear();
  if (!keepSelection) room.selection = { revision: room.selection.revision + 1, shades: {}, changed: {}, screen: undefined };
  if (room.bootstrap === 'pending') room.bootstrap = 'failed';
  room.request = undefined;
  room.notice = key;
  record.messages = record.messages.map((message) => ({ ...message, retryable: false }));
}

let ownerGeneration = 0;
export const useChatConversationStore = create<ChatStore>((set, get) => {
  // Only unpublished copies are mutable. The published record and its nested
  // selection/maps remain unchanged for selectors and in-flight readers.
  const change = (target: ConversationTarget, apply: (draft: ChatConversationState, record: ConversationRecord) => void | false) => {
    set((state) => {
      const record = Object.hasOwn(state.conversations, target.id) ? state.conversations[target.id] : undefined;
      if (!record || record.conversation.deletionState || state.identity?.key !== target.ownerKey ||
          record.conversation.ownerKey !== target.ownerKey) return state;
      const previous = record.conversation;
      const draft = { ...previous, selection: { ...previous.selection,
        shades: { ...previous.selection.shades }, changed: { ...previous.selection.changed } },
        snapshots: new Map(previous.snapshots) };
      const next = { ...record, conversation: draft };
      if (apply(draft, next) === false) return state;
      next.view = readConversationView(draft);
      if (next.messages !== record.messages) next.updatedAt = Date.now();
      return { conversations: { ...state.conversations, [target.id]: next } };
    });
  };
  const matches = (room: ChatConversationState, ticket: ChatRequestTicket) =>
    room.generation === ticket.generation && room.request === ticket.requestId &&
    room.attempt === ticket.attempt && room.snapshots.has(ticket.messageId);
  const releaseRequestDraft = (room: ChatConversationState, record: ConversationRecord, keepDraft = true) => {
    const messageId = room.requestRecovery?.messageId;
    if (!messageId) return;
    const message = record.messages.find((item) => item.id === messageId);
    if (keepDraft && !room.draft && message && !message.automatic) room.draft = message.text;
    room.snapshots.delete(messageId);
    record.messages = record.messages.filter((item) => item.id !== messageId);
  };
  // A list can provide a server ID before the create response binds it to the local draft.
  const roomRecords = (state: ChatStore, room: Readonly<ChatConversationState>) =>
    Object.values(state.conversations).filter(({ conversation }) => conversation.ownerKey === room.ownerKey &&
      (conversation.id === room.id || (room.serverId && conversation.serverId === room.serverId)));
  const dropRoom = (state: ChatStore, room: Readonly<ChatConversationState>) => {
    const conversations = { ...state.conversations };
    const latest = { ...state.latest };
    for (const { conversation } of roomRecords(state, room)) {
      delete conversations[conversation.id];
      const key = subjectKey(conversation.subject);
      if (latest[key] === conversation.id) delete latest[key];
    }
    return {
      conversations, latest,
      removedServerRooms: room.serverId ? new Set([...state.removedServerRooms, room.serverId]) : state.removedServerRooms,
    };
  };
  const markRoomDeletion = (room: ChatConversationState, status: 'pending' | 'failed') => {
    room.deletionState = status;
    room.generation += 1;
    room.request = undefined;
    room.snapshots = new Map();
  };
  const updateRoomDeletion = (state: ChatStore, room: Readonly<ChatConversationState>, status: 'pending' | 'failed') => {
    const conversations = { ...state.conversations };
    for (const record of roomRecords(state, room)) {
      const conversation = { ...record.conversation };
      if (status === 'pending') markRoomDeletion(conversation, status);
      else conversation.deletionState = status;
      conversations[conversation.id] = { ...record, conversation, view: readConversationView(conversation) };
    }
    return { conversations };
  };
  return {
    conversations: {},
    latest: {},
    removedServerRooms: new Set(),
    activate: (userId) => set((state) => state.identity?.userId === userId ? state : {
      identity: { userId, key: `${userId ?? 'guest'}:${++ownerGeneration}` },
      memoryPolicyVersion: undefined,
      conversations: {},
      latest: {},
      removedServerRooms: new Set(),
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
          (room.selection.screen || room.entryProduct?.shadeId !== screen.shadeId || room.entryProduct?.optionId !== screen.optionId)) {
          change(room, (draft) => {
            draft.entryProduct = screen;
            draft.selection.revision += 1;
            draft.dismissedClarificationId = draft.pendingClarification?.id ?? draft.dismissedClarificationId;
            draft.pendingClarification = undefined;
            draft.selection.screen = undefined;
            draft.selection.changed[entry.productId] = draft.selection.revision;
            if (entry.shadeId) draft.selection.shades[entry.productId] = entry.shadeId;
            else delete draft.selection.shades[entry.productId];
          });
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
      const { identity, conversations, latest } = get();
      const record = Object.hasOwn(conversations, id) ? conversations[id] : undefined;
      if (!record || record.conversation.deletionState || record.conversation.ownerKey !== identity?.key) return false;
      set({ latest: { ...latest, [subjectKey(record.conversation.subject)]: id } });
      return true;
    },
    mergeServerRooms: (ownerKey, rooms) => set((state) => {
      if (state.identity?.key !== ownerKey || !state.identity.userId) return state;
      const conversations = { ...state.conversations };
      for (const summary of rooms) {
        if (state.removedServerRooms.has(summary.conversationId)) continue;
        const updatedAt = Date.parse(summary.updatedAt);
        const existing = Object.values(conversations).find(({ conversation }) => conversation.serverId === summary.conversationId);
        if (existing) {
          const room = existing.conversation;
          if (room.deletionState || summary.conversationVersion < room.serverVersion) continue;
          const serverVersion = room.serverSummary ? summary.conversationVersion : room.serverVersion;
          const nextUpdatedAt = Number.isFinite(updatedAt) ? Math.max(updatedAt, existing.updatedAt) : existing.updatedAt;
          if (serverVersion !== room.serverVersion || nextUpdatedAt !== existing.updatedAt ||
              summary.listSummary !== existing.listSummary) {
            conversations[room.id] = { ...existing, conversation: { ...room, serverVersion },
              updatedAt: nextUpdatedAt, listSummary: summary.listSummary };
          }
          continue;
        }
        const room = createChatConversation(state.identity.userId, ownerKey, summary.subject, true);
        room.id = summary.conversationId;
        room.serverId = summary.conversationId;
        room.serverVersion = summary.conversationVersion;
        room.serverSummary = true;
        conversations[room.id] = { conversation: room, messages: [], view: readConversationView(room),
          updatedAt: Number.isFinite(updatedAt) ? updatedAt : Date.now(), listSummary: summary.listSummary };
      }
      return { conversations };
    }),
    restoreServerRoom: ({ id, ownerKey }, detail, generation, reload, committedRequestId) => {
      const state = get();
      if (state.identity?.key !== ownerKey || !state.identity.userId) return;
      const existing = state.conversations[id];
      if (!existing) return;
      const previous = existing.conversation;
      if (previous.ownerKey !== ownerKey || previous.serverId !== detail.conversationId ||
          previous.deletionState || previous.generation !== generation ||
          detail.conversationVersion < previous.serverVersion) return;
      if (committedRequestId && (previous.requestRecovery?.requestId !== committedRequestId ||
          previous.requestRecovery.status !== 'checking')) return;
      if (!committedRequestId && isRequestRecoveryPending(previous.requestRecovery)) return previous.id;
      if (previous.request || (!previous.serverSummary && !reload && detail.conversationVersion === previous.serverVersion)) return previous.id;
      const room = createChatConversation(state.identity.userId, ownerKey, detail.subject, true);
      room.id = previous.id;
      room.draft = previous.draft;
      room.category = previous.category;
      room.requestRecovery = committedRequestId ? undefined : previous.requestRecovery;
      room.generation = previous.generation + 1;
      room.serverId = detail.conversationId;
      room.serverVersion = detail.conversationVersion;
      room.persistenceMode = 'enabled';
      room.serverSummary = false;
      room.olderMessageCursor = detail.nextMessageCursor ?? undefined;
      const product = detail.context.product;
      if (product?.selectedProductId) room.selection.screen = { screenId: 'chat', productId: product.selectedProductId,
        ...(product.selectedShadeId ? { shadeId: product.selectedShadeId } : {}),
        ...(product.selectedOptionId ? { optionId: product.selectedOptionId } : {}) };
      if (product?.selectedProductId && product.selectedShadeId) room.selection.shades[product.selectedProductId] = product.selectedShadeId;
      const style = detail.context.style;
      room.styleContext = style ? { kind: style.kind, lookId: style.lookId,
        recipeId: style.recipeId, recipeVersion: style.recipeVersion, currentStep: style.currentStep } : undefined;
      room.styleConditions = detail.context.style?.conditions ?? detail.context.styleConditions ?? [];
      const messages: ChatMessage[] = detail.messages.map((item) => ({
        ...item.displayPayload, id: item.id, role: item.role, text: item.text,
        ownerKey, generation: room.generation,
      }));
      if (messages.some(message => !message.consultation && !message.compound && !message.ownedLookOptions && message.products?.length) &&
          (!product?.historicalCandidateRefs?.length || product.filters?.optionSearch)) {
        room.notice = 'chat.session.newSearchHint';
      }
      const updatedAt = Date.parse(detail.updatedAt ?? '');
      const record = { conversation: room, messages, view: readConversationView(room), listSummary: existing.listSummary,
        updatedAt: Number.isFinite(updatedAt) ? Math.max(updatedAt, existing.updatedAt) : existing.updatedAt };
      set((current) => current.identity?.key === ownerKey ? {
        conversations: { ...current.conversations, [room.id]: record },
      } : current);
      return get().identity?.key === ownerKey ? room.id : undefined;
    },
    removeMissingServerRoom: (expected) => {
      const state = get();
      const room = state.conversations[expected.id]?.conversation;
      if (!expected.serverId || room?.deletionState || state.identity?.key !== expected.ownerKey || room?.ownerKey !== expected.ownerKey ||
          room.serverId !== expected.serverId || room.generation !== expected.generation ||
          room.serverVersion !== expected.serverVersion) return false;
      set(dropRoom(state, room));
      return true;
    },
    restoreRoomDeletions: (ownerKey, serverIds) => set((state) => {
      const owner = state.identity;
      if (owner?.key !== ownerKey || !owner.userId || !serverIds.length) return state;
      const conversations = { ...state.conversations };
      for (const id of serverIds) {
        if (state.removedServerRooms.has(id)) continue;
        const existing = Object.values(conversations).filter(({ conversation }) => conversation.serverId === id);
        if (existing.length) {
          for (const record of existing) {
            if (record.conversation.deletionState) continue;
            const conversation = { ...record.conversation };
            markRoomDeletion(conversation, 'failed');
            conversations[conversation.id] = { ...record, conversation, view: readConversationView(conversation) };
          }
          continue;
        }
        const conversation = createChatConversation(owner.userId, ownerKey, { type: 'general' }, true);
        conversation.id = id;
        conversation.serverId = id;
        conversation.deletionState = 'failed';
        conversations[id] = { conversation, messages: [], view: readConversationView(conversation),
          updatedAt: Date.now(), recoveredDeletion: true };
      }
      return { conversations };
    }),
    clearRecoveredRoomDeletions: () => set((state) => ({
      conversations: Object.fromEntries(Object.entries(state.conversations).filter(([, record]) =>
        !record.recoveredDeletion || record.conversation.deletionState === 'pending')),
    })),
    clearRequestRecoveries: () => {
      for (const { conversation } of Object.values(get().conversations)) {
        if (!conversation.requestRecovery) continue;
        change(conversation, (room, record) => {
          releaseRequestDraft(room, record, false);
          room.requestRecovery = undefined;
        });
      }
    },
    beginRoomDeletion: (target) => {
      const state = get();
      const record = state.conversations[target.id];
      const room = record?.conversation;
      if (!room || state.identity?.key !== target.ownerKey || room.ownerKey !== target.ownerKey ||
          room.deletionState === 'pending' || !canDeleteRoom(room)) return;
      const patch = updateRoomDeletion(state, room, 'pending');
      set(patch);
      return patch.conversations[room.id].conversation;
    },
    finishRoomDeletion: (expected, completed) => set((state) => {
      const record = state.conversations[expected.id];
      const room = record?.conversation;
      if (state.identity?.key !== expected.ownerKey || room?.ownerKey !== expected.ownerKey ||
          room.serverId !== expected.serverId || room.generation !== expected.generation ||
          room.deletionState !== 'pending') return state;
      if (completed) return dropRoom(state, room);
      return updateRoomDeletion(state, room, 'failed');
    }),
    prependServerMessages: (target, cursor, detail) => { change(target, (room, record) => {
      if (room.olderMessageCursor !== cursor || room.serverId !== detail.conversationId) return false;
      const ids = new Set(record.messages.map((message) => message.id));
      const older: ChatMessage[] = detail.messages.filter((item) => !ids.has(item.id)).map((item) => ({
        ...item.displayPayload, id: item.id, role: item.role, text: item.text,
        ownerKey: room.ownerKey, generation: room.generation,
      }));
      record.messages = [...older, ...record.messages];
      room.olderMessageCursor = detail.nextMessageCursor ?? undefined;
    }); },
    setDraft: (target, value) => { change(target, (room) => { room.draft = value; }); },
    setCategory: (target, value) => { change(target, (room) => {
      if (room.category !== value) room.styleRevision += 1;
      room.category = value;
    }); },
    setNotice: (target, value) => { change(target, (room) => { room.notice = value; }); },
    setPersistenceMode: (target, value) => { change(target, (room) => { room.persistenceMode = value; }); },
    bindServerRoom: (target, id, version) => {
      const state = get();
      const room = state.conversations[target.id]?.conversation;
      if (!room || state.identity?.key !== target.ownerKey || room.ownerKey !== target.ownerKey ||
          room.deletionState || (room.serverId && room.serverId !== id)) return;
      if (state.removedServerRooms.has(id)) {
        set(dropRoom(state, room));
        return;
      }
      const deleting = roomRecords(state, { ...room, serverId: id })
        .find(({ conversation }) => conversation.deletionState)?.conversation.deletionState;
      change(target, (draft) => {
        draft.serverId = id;
        draft.serverVersion = Math.max(draft.serverVersion, version);
        if (deleting) markRoomDeletion(draft, deleting);
      });
    },
    observeMemoryPolicy: (ownerKey, settings, force = false) => {
      const { identity, memoryPolicyVersion: previous } = get();
      if (identity?.key !== ownerKey || (previous !== undefined && settings.version < previous)) return;
      if (previous !== settings.version) set({ memoryPolicyVersion: settings.version });
      if (force || (previous === undefined ? !settings.enabled : previous !== settings.version)) {
        get().invalidateMemoryContext(ownerKey, previous === undefined && !force);
      }
    },
    invalidateMemoryContext: (ownerKey, preserveFirstRequest = false) => {
      for (const record of Object.values(get().conversations)) {
        if (record.conversation.ownerKey !== ownerKey) continue;
        change(record.conversation, (room, next) => {
          if (preserveFirstRequest && room.subject.type === 'general' && room.serverVersion === 0 &&
              !room.beautyContext && !room.entryProduct && !room.styleContext && !room.selection.screen &&
              !next.messages.some((message) => message.role === 'assistant')) return false;
          resetRoom(room, next, 'chat.session.newSearchHint');
          next.messages = next.messages.map((message) => message.appliedMemories
            ? { ...message, appliedMemories: undefined } : message);
          room.entryProduct = undefined;
          room.styleContext = undefined;
          room.styleRevision += 1;
        });
      }
    },
    setStyle: (target, value) => { change(target, (room) => {
      room.styleContext = value ? { ...value } : undefined;
      room.styleRevision += 1;
      room.category = value ? 'style' : room.subject.type === 'product' || room.entryProduct ? 'product' : undefined;
    }); },
    clearProduct: (target) => { change(target, (room, record) => {
      room.entryProduct = undefined;
      resetRoom(room, record, 'chat.session.newSearchHint');
    }); },
    resetSession: (target, key, keepSelection) => { change(target, (room, record) => resetRoom(room, record, key, keepSelection)); },
    selectProduct: (target, productId, message) => { change(target, (room) => {
      if (message.ownerKey !== room.ownerKey || message.generation !== room.generation) return false;
      const current = room.beautyContext;
      if (!current?.session || isChatSessionExpired(current.session.expiresAt) ||
        message.resultSetId !== current.session.resultSetId || !current.candidateIds.includes(productId)) return false;
      room.selection.revision += 1;
      room.dismissedClarificationId = room.pendingClarification?.id ?? room.dismissedClarificationId;
      room.pendingClarification = undefined;
      const shadeId = room.selection.shades[productId];
      room.selection.screen = { screenId: 'chat', productId, ...(shadeId ? { shadeId } : {}) };
      room.beautyContext = { ...current, selectedProductId: productId };
    }); },
    selectShade: (target, productId, shadeId, message) => { change(target, (room) => {
      if (message.ownerKey !== room.ownerKey || message.generation !== room.generation) return false;
      const currentSession = room.beautyContext?.session;
      if (currentSession && (isChatSessionExpired(currentSession.expiresAt) || message.resultSetId !== currentSession.resultSetId)) return false;
      room.dismissedClarificationId = room.pendingClarification?.id ?? room.dismissedClarificationId;
      room.pendingClarification = undefined;
      const revision = room.selection.revision + 1;
      const shades = { ...room.selection.shades, [productId]: shadeId };
      room.selection = { revision, shades, changed: { ...room.selection.changed, [productId]: revision },
        screen: { screenId: 'chat', productId, shadeId } };
      const source = room.beautyContext ?? (message.ownerKey === room.ownerKey &&
        message.generation === room.generation ? message.chatContext : undefined);
      // Keep the latest candidate numbering; screenContext can identify an older selected card.
      if (source?.candidateIds.includes(productId)) {
        room.beautyContext = { ...source, selectedProductId: productId,
          shadeSelections: { ...source.shadeSelections, [productId]: shadeId } };
      } else if (!room.beautyContext) room.beautyContext = source;
    }); },
    setRecipeStep: (target, messageId, index) => { change(target, (room, record) => {
      const message = record.messages.find((item) => item.id === messageId);
      const recipe = message?.styleRecipe;
      if (!recipe || room.request || message.ownerKey !== room.ownerKey ||
          message.generation !== room.generation || index < 0 || !Number.isInteger(index) || index >= recipe.steps.length ||
          recipe.recipeId !== room.styleContext?.recipeId || recipe.recipeVersion !== room.styleContext?.recipeVersion) return false;
      room.styleRevision += 1;
      room.styleContext = { kind: recipe.kind, lookId: recipe.lookId,
        recipeId: recipe.recipeId, recipeVersion: recipe.recipeVersion, currentStep: index };
      record.messages = record.messages.map((item) => item.id === messageId
        ? { ...item, styleRecipe: { ...recipe, currentStep: index } } : item);
    }); },
    beginRequest: (target, proposed, retryId) => {
      let ticket: ChatRequestTicket | undefined;
      change(target, (room, record) => {
        if (room.request || isRequestRecoveryPending(room.requestRecovery)) return false;
        const snapshot = retryId ? room.snapshots.get(retryId) : proposed;
        const retry = retryId ? record.messages.find((message) => message.id === retryId) : undefined;
        if (!snapshot || snapshot.generation !== room.generation ||
            snapshot.args.expectedUserId !== room.userId ||
            (retryId && (!retry?.failed || !retry.retryable))) return false;
        const messageId = retryId ?? `user-${++room.serial}`;
        room.snapshots.set(messageId, snapshot);
        room.request = snapshot.args.requestId;
        room.requestRecovery = undefined;
        if (room.notice === 'chat.cancel.done') room.notice = undefined;
        room.attempt += 1;
        if (snapshot.automatic) room.bootstrap = 'pending';
        if (room.draft.trim() === snapshot.args.message) room.draft = '';
        record.messages = retryId
          ? record.messages.map((message) => message.id === messageId ? { ...message, failed: false } : message)
          : [...record.messages, { id: messageId, role: 'user', text: snapshot.args.message,
            automatic: snapshot.automatic, category: snapshot.args.category, ownerKey: room.ownerKey, generation: room.generation }];
        ticket = { ...target, messageId, requestId: room.request, generation: room.generation, attempt: room.attempt };
      });
      return ticket;
    },
    beginRequestRecovery: (target, requestId, ticket) => {
      let started: Readonly<ChatConversationState> | undefined;
      change(target, (room) => {
        if (!room.serverId || room.serverId !== target.serverId || room.generation !== target.generation ||
            room.requestRecovery?.status === 'checking') return false;
        if (isRequestRecoveryPending(room.requestRecovery) && room.requestRecovery?.requestId !== requestId) return false;
        if (ticket) {
          if (ticket.requestId !== requestId || !matches(room, ticket)) return false;
          room.request = undefined;
          if (room.bootstrap === 'pending') room.bootstrap = 'failed';
        } else if (room.request) return false;
        const messageId = ticket?.messageId ??
          (room.requestRecovery?.requestId === requestId ? room.requestRecovery.messageId : undefined);
        room.requestRecovery = { requestId, status: 'checking', messageId };
        started = room;
      });
      return started;
    },
    finishRequestRecovery: (expected, status) => {
      let applied = false;
      change(expected, (room, record) => {
        const previous = expected.requestRecovery;
        if (!previous || room.requestRecovery !== previous || room.generation !== expected.generation ||
            room.serverId !== expected.serverId) return false;
        if (status === 'interrupted' || status === 'failed' || status === 'dismissed') releaseRequestDraft(room, record);
        room.requestRecovery = status === 'dismissed' ? undefined : { ...previous, status };
        applied = true;
      });
      return applied;
    },
    confirmCancellation: (expected, version) => {
      let applied = false;
      change(expected, (room, record) => {
        if (!expected.requestRecovery || room.requestRecovery !== expected.requestRecovery ||
            room.generation !== expected.generation || room.serverId !== expected.serverId ||
            !Number.isSafeInteger(version) || version < room.serverVersion) return false;
        releaseRequestDraft(room, record);
        room.requestRecovery = undefined;
        room.serverVersion = version;
        room.notice = 'chat.cancel.done';
        applied = true;
      });
      return applied;
    },
    completeRequest: (ticket, response, question) => {
      let applied = false;
      change(ticket, (room, record) => {
        if (!matches(room, ticket)) return false;
        if (room.serverId && response.conversation) {
          if (response.conversation.id !== room.serverId) return false;
          room.serverVersion = Math.max(room.serverVersion, response.conversation.version);
        }
        const { messageId } = ticket;
        const snapshot = room.snapshots.get(messageId)!;
        if (snapshot.automatic) room.bootstrap = 'ready';
        if (room.styleRevision === snapshot.styleRevision) {
          const expected = snapshot.args.styleContext;
          const next = response.styleContext;
          if (next && expected && next.kind === expected.kind && next.lookId === expected.lookId) {
            room.styleContext = { ...next };
          }
          if (snapshot.args.styleSearch && response.styleConditions) {
            room.styleConditions = response.styleConditions.map((item) => ({ ...item }));
          }
        }
        if (response.styleCandidates && room.styleRevision === snapshot.styleRevision) room.category = 'style';
        const requestTurn = Number(messageId.slice('user-'.length));
        if (response.sessionStatus === 'unavailable' && requestTurn >= room.beautyContextTurn) {
          resetRoom(room, record, 'chat.session.unavailable', room.selection.revision > snapshot.revision);
        } else if (response.chatContext && requestTurn >= room.beautyContextTurn) {
          const next = response.chatContext;
          const current = room.beautyContext?.session;
          const olderVersion = current && next.session?.sessionId === current.sessionId &&
            next.session.stateVersion < current.stateVersion;
          if (!olderVersion) {
            const shades = { ...next.shadeSelections };
            for (const pid of next.candidateIds) {
              if ((room.selection.changed[pid] ?? 0) > snapshot.revision) shades[pid] = room.selection.shades[pid];
            }
            const latestProduct = room.selection.screen?.productId;
            room.beautyContext = { ...next,
              ...(Object.keys(shades).length ? { shadeSelections: shades } : {}),
              ...(room.selection.revision > snapshot.revision && latestProduct && next.candidateIds.includes(latestProduct)
                ? { selectedProductId: latestProduct } : {}) };
            const nextShades = { ...room.selection.shades };
            for (const pid of next.candidateIds) {
              if (shades[pid]) nextShades[pid] = shades[pid]; else delete nextShades[pid];
            }
            room.selection.shades = nextShades;
            if (room.selection.revision === snapshot.revision && room.selection.screen &&
              (!next.candidateIds.includes(room.selection.screen.productId ?? '') ||
               shades[room.selection.screen.productId ?? ''] !== room.selection.screen.shadeId)) {
              room.selection.screen = undefined;
            }
            room.beautyContextTurn = requestTurn;
            room.notice = undefined;
          }
        }

        if (response.pendingClarification && room.selection.revision !== snapshot.revision) {
          room.dismissedClarificationId = response.pendingClarification.id;
        }
        if (room.selection.revision === snapshot.revision && response.sessionStatus) {
          const pending = response.pendingClarification;
          room.pendingClarification = pending?.id === room.dismissedClarificationId ? undefined : pending ?? undefined;
        }
        room.snapshots.delete(messageId);
        const answer: ChatMessage = {
          id: `assistant-${++room.serial}`, role: 'assistant', text: response.answer,
          products: snapshot.generalMakeup && !response.resultType ? [] : response.products,
          question,
          category: response.styleRecipe || snapshot.generalMakeup ? 'style'
            : response.resultType === 'recommendations' || response.resultType === 'product_detail' || response.resultType === 'empty' ? 'product' : snapshot.args.category,
          ownerKey: room.ownerKey, generation: snapshot.generation, sessionStatus: response.sessionStatus,
          resultSetId: response.chatContext?.session?.resultSetId,
          screenContext: snapshot.args.screenContext,
          chatContext: response.chatContext ? { ...response.chatContext, session: undefined } : undefined, evidence: response.evidence,
          resultType: response.resultType, ingredientResults: response.ingredientResults,
          fragranceSearchSummary: response.fragranceSearchSummary,
          ingredientComparison: response.ingredientComparison,
          styleRecipe: response.styleRecipe,
          styleCandidates: response.styleCandidates,
          styleStatus: response.styleStatus,
          memoryProposal: response.memoryProposal,
          ...(response.appliedMemories?.length ? { appliedMemories: response.appliedMemories } : {}),
          ...(response.knowledge ? { knowledge: response.knowledge } : {}),
          optionSearch: response.optionSearch,
          consultation: response.consultation,
          ownedLookOptions: response.ownedLookOptions,
          ...(response.compound ? { compound: response.compound } : {}),
        };
        record.messages = ((current: ChatMessage[]) => {
          const questionIndex = current.findIndex((message) => message.id === messageId);
          return questionIndex < 0 ? current : [
            ...current.slice(0, questionIndex + 1), answer, ...current.slice(questionIndex + 1),
          ];
        })(record.messages);
        room.request = undefined;
        applied = true;
      });
      return applied;
    },
    failRequest: (ticket, errorKey, fatal, ownerError, clarificationConflict = false) => { change(ticket, (room, record) => {
      if (!matches(room, ticket)) return false;
      const { messageId } = ticket;
      const snapshot = room.snapshots.get(messageId)!;
      if (snapshot.automatic) room.bootstrap = 'failed';
      if (fatal) {
        const oldTurn = Number(messageId.slice('user-'.length)) < room.beautyContextTurn;
        if (oldTurn && room.beautyContext?.session && !ownerError) {
          room.snapshots.clear();
          record.messages = record.messages.map((message) => ({ ...message, retryable: false }));
          room.notice = errorKey;
        } else resetRoom(room, record, errorKey);
      }
      record.messages = record.messages.map((message) => message.id === messageId
        ? { ...message, failed: true, errorKey, retryable: !fatal && !clarificationConflict } : message);
      if (clarificationConflict) {
        room.dismissedClarificationId = room.pendingClarification?.id ?? room.dismissedClarificationId;
        room.pendingClarification = undefined;
        room.snapshots.delete(messageId);
      }
      if (!snapshot.automatic && !room.draft) room.draft = snapshot.args.message;
      room.request = undefined;
    }); },
  };
});
