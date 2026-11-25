import AsyncStorage from '@react-native-async-storage/async-storage';
import { useEffect, useRef, useState } from 'react';
import { ApiError, apiChatUserRequest } from '@/lib/api';
import { chatRequestRecoveryKey, chatRequestRecoveryPrefix, chatRoomDeletionKey, chatRoomDeletionPrefix } from '@/lib/storage';
import { isRequestRecoveryPending, useChatConversationStore } from '@/store/chatConversationStore';
import type { ChatRequestTicket, ServerConversationDetail, ServerConversationSummary } from '@/types/chatConversation';

const emptyStatus = {
  listLoading: false, listError: false, detailLoading: false, detailError: false, cursor: null as string | null,
};
const persistedId = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;

type RequestStatusResponse = {
  requestId: string;
  status: string;
  response?: { conversation?: { id: string; version: number; persistenceStatus: string } };
};

export function useChatConversations(userId: string | null, ownerKey?: string) {
  const [status, setStatus] = useState<(typeof emptyStatus & { ownerKey: string })>();
  const { listLoading, listError, detailLoading, detailError, cursor } = status && status.ownerKey === ownerKey ? status : emptyStatus;
  const identity = useRef({ userId, ownerKey });
  const listing = useRef(false);
  const reading = useRef(false);
  const refreshing = useRef(new Set<string>());
  const restoredDeletions = useRef<string>(undefined);
  useEffect(() => {
    identity.current = { userId, ownerKey };
    listing.current = false;
    reading.current = false;
    refreshing.current = new Set();
    return () => { identity.current = { userId: null, ownerKey: undefined }; };
  }, [userId, ownerKey]);

  const active = () => {
    const owner = useChatConversationStore.getState().identity;
    return !!ownerKey && identity.current.userId === userId &&
      identity.current.ownerKey === ownerKey && owner?.key === ownerKey && owner.userId === userId;
  };
  const current = () => !!userId && active();

  const updateStatus = (patch: Partial<typeof emptyStatus>) => {
    if (!ownerKey) return;
    setStatus((previous) => ({ ...(previous?.ownerKey === ownerKey ? previous : emptyStatus), ...patch, ownerKey }));
  };

  const list = async (more = false) => {
    if (!current() || listing.current || (more && !cursor)) return;
    listing.current = true;
    updateStatus({ listLoading: true, listError: false, ...(!more && !reading.current ? { detailError: false } : {}) });
    try {
      if (restoredDeletions.current !== ownerKey) {
        const prefix = chatRoomDeletionPrefix(userId!);
        const keys = await AsyncStorage.getAllKeys();
        if (!current()) return;
        const roomIds = keys.filter((key) => key.startsWith(prefix))
          .map((key) => key.slice(prefix.length)).filter((id) => persistedId.test(id));
        useChatConversationStore.getState().restoreRoomDeletions(ownerKey!, roomIds);
        restoredDeletions.current = ownerKey;
      }
      const query = more && cursor ? `?cursor=${encodeURIComponent(cursor)}` : '';
      const result = await apiChatUserRequest<{ conversations: ServerConversationSummary[]; nextCursor: string | null }>(
        `/api/chat/conversations${query}`, 'GET', userId!,
      );
      if (!current()) return;
      useChatConversationStore.getState().mergeServerRooms(ownerKey!, result.conversations);
      updateStatus({ cursor: result.nextCursor });
    } catch (err) {
      if (current() && !(err instanceof ApiError && err.code === 'persistence_disabled')) updateStatus({ listError: true });
    } finally {
      if (current()) { listing.current = false; updateStatus({ listLoading: false }); }
    }
  };

  const recoverRequest = async (id: string, requestId: string, ticket?: ChatRequestTicket, stillSelected?: () => boolean) => {
    const store = useChatConversationStore.getState();
    const room = store.conversations[id]?.conversation;
    if ((!ticket && !current()) || !room?.userId || !room.serverId || room.ownerKey !== ownerKey ||
        store.identity?.key !== ownerKey || room.deletionState) return false;
    const { userId: owner, serverId } = room;
    const recovery = store.beginRequestRecovery(room, requestId, ticket);
    if (!recovery) return false;
    const applicable = () => {
      const latest = useChatConversationStore.getState().conversations[id]?.conversation;
      return current() && (!stillSelected || stillSelected()) && !!latest && !latest.deletionState &&
        latest.requestRecovery === recovery.requestRecovery && latest.generation === recovery.generation;
    };
    const marker = chatRequestRecoveryKey(owner, serverId, requestId);
    const roomPath = `/api/chat/conversations/${encodeURIComponent(serverId)}`;
    let readingDetail = false;
    try {
      if (!applicable()) return false;
      const result = await apiChatUserRequest<RequestStatusResponse>(`${roomPath}/requests/${encodeURIComponent(requestId)}`, 'GET', owner);
      if (!applicable() || result?.requestId !== requestId) return false;
      if (result.status === 'IN_PROGRESS') {
        store.finishRequestRecovery(recovery, 'in_progress');
        return false;
      }
      if (result.status === 'INTERRUPTED' || result.status === 'FAILED') {
        if (store.finishRequestRecovery(recovery, result.status === 'FAILED' ? 'failed' : 'interrupted')) {
          await AsyncStorage.removeItem(marker).catch(() => {});
          return true;
        }
        return false;
      }
      const committed = result.response?.conversation;
      if (result.status !== 'COMMITTED' || committed?.id !== serverId || committed.persistenceStatus !== 'stored' ||
          !Number.isSafeInteger(committed.version) || committed.version < 0) return false;
      readingDetail = true;
      const detail = await apiChatUserRequest<ServerConversationDetail>(roomPath, 'GET', owner);
      if (!applicable() || detail?.conversationId !== serverId || !Number.isSafeInteger(detail.conversationVersion) ||
          detail.conversationVersion < committed.version) return false;
      if (store.restoreServerRoom(recovery, detail, recovery.generation, true, requestId)) {
        await AsyncStorage.removeItem(marker).catch(() => {});
        return true;
      }
    } catch (error) {
      if (applicable() && error instanceof ApiError) {
        if (error.status === 401 || error.status === 403) store.finishRequestRecovery(recovery, 'auth');
        else if (!readingDetail && error.status === 404 && error.code === 'not_found') store.finishRequestRecovery(recovery, 'not_found');
      }
    } finally {
      store.finishRequestRecovery(recovery, 'unconfirmed');
    }
    return false;
  };

  const recover = async (id: string, ticket?: ChatRequestTicket, stillSelected?: () => boolean) => {
    if (ticket) {
      await recoverRequest(id, ticket.requestId, ticket, stillSelected);
      return;
    }
    const room = useChatConversationStore.getState().conversations[id]?.conversation;
    if (!current() || !room?.userId || !room.serverId || room.ownerKey !== ownerKey || room.deletionState || room.request) return;
    const pending = isRequestRecoveryPending(room.requestRecovery) ? room.requestRecovery?.requestId : undefined;
    if (pending && !await recoverRequest(id, pending, undefined, stillSelected)) return;
    const prefix = chatRequestRecoveryPrefix(room.userId, room.serverId);
    let keys: readonly string[];
    try { keys = await AsyncStorage.getAllKeys(); } catch { return; }
    for (const key of keys) {
      if (!key.startsWith(prefix)) continue;
      const requestId = key.slice(prefix.length);
      if (requestId === pending || !persistedId.test(requestId)) continue;
      if (stillSelected && !stillSelected()) return;
      if (!await recoverRequest(id, requestId, undefined, stillSelected)) return;
    }
  };

  const dismissRecovery = async (id: string) => {
    const store = useChatConversationStore.getState();
    const room = store.conversations[id]?.conversation;
    if (!current() || !room?.userId || !room.serverId || room.ownerKey !== ownerKey || room.deletionState ||
        room.requestRecovery?.status !== 'not_found') return;
    try {
      await AsyncStorage.removeItem(chatRequestRecoveryKey(room.userId, room.serverId, room.requestRecovery.requestId));
      if (current() && store.finishRequestRecovery(room, 'dismissed')) await recover(id);
    } catch {
      return;
    }
  };

  const open = async (id: string, mode: 'select' | 'reload' | 'refresh' = 'select', stillSelected?: () => boolean) => {
    const room = useChatConversationStore.getState().conversations[id]?.conversation;
    if (!room || room.deletionState || room.ownerKey !== ownerKey) return;
    if (!room.serverId) return id;
    const refreshes = refreshing.current;
    if (!current() || (mode === 'select' && reading.current) ||
        (mode === 'refresh' && (room.request || reading.current || refreshes.has(room.serverId)))) return;
    if (mode === 'refresh' && isRequestRecoveryPending(room.requestRecovery)) {
      if (room.requestRecovery?.status === 'in_progress' || room.requestRecovery?.status === 'unconfirmed') {
        await recover(id, undefined, stillSelected);
      }
      return;
    }
    if (mode === 'select') {
      reading.current = true;
      updateStatus({ detailLoading: true, detailError: false });
    }
    if (mode === 'refresh') refreshes.add(room.serverId);
    try {
      const detail = await apiChatUserRequest<ServerConversationDetail>(
        `/api/chat/conversations/${room.serverId}`, 'GET', userId!,
      );
      if (!current() || (stillSelected && !stillSelected()) || detail.conversationId !== room.serverId) return;
      const opened = useChatConversationStore.getState().restoreServerRoom(room, detail, room.generation,
        mode === 'reload' || (mode === 'select' && room.notice === 'chat.session.conflict'));
      if (mode !== 'reload' && opened) await recover(opened, undefined, stillSelected);
      if (current() && (!stillSelected || stillSelected())) return opened;
    } catch (err) {
      if (!current() || (stillSelected && !stillSelected())) return;
      const store = useChatConversationStore.getState();
      if (err instanceof ApiError && err.status === 404 && err.code === 'not_found') {
        store.removeMissingServerRoom(room);
        return;
      }
      if (mode === 'select') {
        updateStatus({ detailError: true });
        const unavailable = err instanceof ApiError && (err.code === 'network' || err.status >= 500);
        const latest = store.conversations[id]?.conversation;
        if (unavailable && !room.serverSummary && latest?.generation === room.generation &&
            latest.ownerKey === ownerKey && !latest.deletionState) return id;
      }
    } finally {
      if (mode === 'refresh') refreshes.delete(room.serverId);
      if (mode === 'select' && current()) { reading.current = false; updateStatus({ detailLoading: false }); }
    }
  };
  const older = async (id: string) => {
    if (!current() || reading.current) return;
    const room = useChatConversationStore.getState().conversations[id]?.conversation;
    if (!room?.serverId || room.deletionState || !room.olderMessageCursor || room.ownerKey !== ownerKey) return;
    const before = room.olderMessageCursor;
    reading.current = true;
    updateStatus({ detailLoading: true, detailError: false });
    try {
      const detail = await apiChatUserRequest<ServerConversationDetail>(
        `/api/chat/conversations/${room.serverId}?cursor=${before}`, 'GET', userId!,
      );
      const store = useChatConversationStore.getState();
      if (current() && store.conversations[id]?.conversation.generation === room.generation) {
        store.prependServerMessages({ id, ownerKey: ownerKey! }, before, detail);
      }
    } catch {
      if (current()) updateStatus({ detailError: true });
    } finally {
      if (current()) { reading.current = false; updateStatus({ detailLoading: false }); }
    }
  };

  const remove = async (id: string) => {
    if (!ownerKey || !active()) return;
    const store = useChatConversationStore.getState();
    const room = store.beginRoomDeletion({ id, ownerKey });
    if (!room) return;
    if (!room.serverId || !room.userId) {
      store.finishRoomDeletion(room, true);
      return;
    }
    const marker = chatRoomDeletionKey(room.userId, room.serverId);
    let completed = false;
    try {
      await AsyncStorage.setItem(marker, '1');
      if (useChatConversationStore.getState().identity?.key !== room.ownerKey) return;
      const result = await apiChatUserRequest<unknown>(
        `/api/chat/conversations/${encodeURIComponent(room.serverId)}`, 'DELETE', room.userId,
      );
      completed = result === undefined;
    } catch {
      // Leave a written marker for an explicit retry, even if the response was lost.
    }
    store.finishRoomDeletion(room, completed);
    if (completed) {
      try {
        await AsyncStorage.removeItem(marker);
        const prefix = chatRequestRecoveryPrefix(room.userId, room.serverId);
        const keys = (await AsyncStorage.getAllKeys()).filter((key) => key.startsWith(prefix));
        if (keys.length) await AsyncStorage.multiRemove(keys);
      } catch {
        // A confirmed server deletion stays complete if device cleanup needs another attempt.
      }
    }
  };

  const refresh = async (id?: string) => {
    await Promise.all([list(), id ? open(id, 'refresh') : undefined]);
  };

  return {
    list, open, older, remove, refresh, recover, dismissRecovery, detailLoading, detailError,
    loading: listLoading || detailLoading, error: listError || detailError, hasMore: !!cursor,
  };
}
