import { uuid } from 'expo';
import { create } from 'zustand';
import type { TranslationKey } from '@/lib/i18n';
import type { PendingClarification, RecentChatMessage, BeautyChatContext, ChatResponse, ChatScreenContext, ChatStyleContext, ChatStyleCondition } from '@/types';
import type { ChatCategory, ChatMessage, ConversationTarget, ChatRequestTicket, ChatRequestSnapshot, ConversationEntry, ConversationSubject, ServerConversationSummary, ServerConversationDetail } from '@/types/chatConversation';

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
  return { screenId: 'product-detail', productId: entry.productId, ...(entry.shadeId ? { shadeId: entry.shadeId } : {}) };
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
    draft: '',
    notice: undefined as TranslationKey | undefined,
    request: undefined as string | undefined,
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
};

type ChatStore = {
  identity?: { userId: string | null; key: string };
  conversations: Record<string, ConversationRecord>;
  latest: Record<string, string>;
  activate: (userId: string | null) => void;
  open: (entry: ConversationEntry, fresh?: boolean, focus?: { product?: ChatScreenContext; style?: ChatStyleContext }) => string | undefined;
  resume: (id: string) => boolean;
  mergeServerRooms: (ownerKey: string, rooms: ServerConversationSummary[]) => void;
  restoreServerRoom: (ownerKey: string, detail: ServerConversationDetail, refreshGeneration?: number) => string | undefined;
  prependServerMessages: (target: ConversationTarget, cursor: number, detail: ServerConversationDetail) => void;
  setDraft: (target: ConversationTarget, value: string) => void;
  setCategory: (target: ConversationTarget, value: ChatCategory) => void;
  setNotice: (target: ConversationTarget, value: TranslationKey) => void;
  setPersistenceMode: (target: ConversationTarget, value: 'enabled' | 'disabled') => void;
  bindServerRoom: (target: ConversationTarget, id: string, version: number) => void;
  invalidateMemoryContext: (ownerKey: string) => void;
  setStyle: (target: ConversationTarget, value?: ChatStyleContext) => void;
  clearProduct: (target: ConversationTarget) => void;
  resetSession: (target: ConversationTarget, key: TranslationKey, keepSelection?: boolean) => void;
  selectProduct: (target: ConversationTarget, productId: string, message: ChatMessage) => void;
  selectShade: (target: ConversationTarget, productId: string, shadeId: string, message: ChatMessage) => void;
  setRecipeStep: (target: ConversationTarget, messageId: string, index: number) => void;
  beginRequest: (target: ConversationTarget, snapshot: ChatRequestSnapshot, retryId?: string) => ChatRequestTicket | undefined;
  completeRequest: (ticket: ChatRequestTicket, response: ChatResponse, question: string) => void;
  failRequest: (ticket: ChatRequestTicket, key: TranslationKey, fatal: boolean, ownerError: boolean, clarificationConflict?: boolean) => void;
};

function resetRoom(room: ChatConversationState, record: ConversationRecord, key: TranslationKey, keepSelection = false) {
  room.generation += 1;
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
      if (!record || state.identity?.key !== target.ownerKey ||
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
  return {
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
          (room.selection.screen || room.entryProduct?.shadeId !== screen.shadeId)) {
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
      if (!record || record.conversation.ownerKey !== identity?.key) return false;
      set({ latest: { ...latest, [subjectKey(record.conversation.subject)]: id } });
      return true;
    },
    mergeServerRooms: (ownerKey, rooms) => set((state) => {
      if (state.identity?.key !== ownerKey || !state.identity.userId) return state;
      const conversations = { ...state.conversations };
      for (const summary of rooms) {
        if (Object.values(conversations).some((record) => record.conversation.serverId === summary.conversationId)) continue;
        const room = createChatConversation(state.identity.userId, ownerKey, summary.subject, true);
        room.id = summary.conversationId;
        room.serverId = summary.conversationId;
        room.serverVersion = summary.conversationVersion;
        room.serverSummary = true;
        conversations[room.id] = { conversation: room, messages: [], view: readConversationView(room), updatedAt: Date.parse(summary.updatedAt) || Date.now() };
      }
      return { conversations };
    }),
    restoreServerRoom: (ownerKey, detail, refreshGeneration) => {
      const state = get();
      if (state.identity?.key !== ownerKey || !state.identity.userId) return;
      const existing = Object.values(state.conversations).find((record) => record.conversation.serverId === detail.conversationId);
      const previous = existing?.conversation;
      if (refreshGeneration === undefined) {
        if (previous && (!previous.serverSummary || previous.request)) return previous.id;
      } else if (!previous || previous.request || previous.generation !== refreshGeneration ||
          previous.serverVersion > detail.conversationVersion) return;
      const room = createChatConversation(state.identity.userId, ownerKey, detail.subject, true);
      room.id = previous?.id ?? detail.conversationId;
      if (previous && refreshGeneration !== undefined) {
        room.draft = previous.draft;
        room.category = previous.category;
        room.generation = refreshGeneration + 1;
      }
      room.serverId = detail.conversationId;
      room.serverVersion = detail.conversationVersion;
      room.persistenceMode = 'enabled';
      room.serverSummary = false;
      room.olderMessageCursor = detail.nextMessageCursor ?? undefined;
      const product = detail.context.product;
      if (product?.selectedProductId) room.selection.screen = { screenId: 'chat', productId: product.selectedProductId,
        ...(product.selectedShadeId ? { shadeId: product.selectedShadeId } : {}) };
      if (product?.selectedProductId && product.selectedShadeId) room.selection.shades[product.selectedProductId] = product.selectedShadeId;
      const style = detail.context.style;
      room.styleContext = style ? { kind: style.kind, lookId: style.lookId,
        recipeId: style.recipeId, recipeVersion: style.recipeVersion, currentStep: style.currentStep } : undefined;
      room.styleConditions = detail.context.style?.conditions ?? detail.context.styleConditions ?? [];
      const messages: ChatMessage[] = detail.messages.map((item) => ({
        ...item.displayPayload, id: item.id, role: item.role, text: item.text,
        ownerKey, generation: room.generation,
      }));
      const record = { conversation: room, messages, view: readConversationView(room),
        updatedAt: (detail.updatedAt ? Date.parse(detail.updatedAt) : 0) || existing?.updatedAt || Date.now() };
      set((current) => current.identity?.key === ownerKey ? {
        conversations: { ...current.conversations, [room.id]: record },
        latest: { ...current.latest, [subjectKey(room.subject)]: room.id },
      } : current);
      return get().identity?.key === ownerKey ? room.id : undefined;
    },
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
    bindServerRoom: (target, id, version) => { change(target, (room) => {
      if (room.serverId && room.serverId !== id) return false;
      room.serverId = id;
      room.serverVersion = Math.max(room.serverVersion, version);
    }); },
    invalidateMemoryContext: (ownerKey) => {
      for (const record of Object.values(get().conversations)) {
        if (record.conversation.ownerKey !== ownerKey) continue;
        change(record.conversation, (room, next) => {
          resetRoom(room, next, 'chat.session.newSearchHint');
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
        if (room.request) return false;
        const snapshot = retryId ? room.snapshots.get(retryId) : proposed;
        const retry = retryId ? record.messages.find((message) => message.id === retryId) : undefined;
        if (!snapshot || snapshot.generation !== room.generation ||
            snapshot.args.expectedUserId !== room.userId ||
            (retryId && (!retry?.failed || !retry.retryable))) return false;
        const messageId = retryId ?? `user-${++room.serial}`;
        room.snapshots.set(messageId, snapshot);
        room.request = snapshot.args.requestId;
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
    completeRequest: (ticket, response, question) => { change(ticket, (room, record) => {
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
          ...(response.knowledge ? { knowledge: response.knowledge } : {}),
          optionSearch: response.optionSearch,
        };
        record.messages = ((current: ChatMessage[]) => {
          const questionIndex = current.findIndex((message) => message.id === messageId);
          return questionIndex < 0 ? current : [
            ...current.slice(0, questionIndex + 1), answer, ...current.slice(questionIndex + 1),
          ];
        })(record.messages);
        room.request = undefined;
    }); },
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
