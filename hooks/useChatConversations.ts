import { useEffect, useRef, useState } from 'react';
import { ApiError, apiChatUserRequest } from '@/lib/api';
import { useChatConversationStore } from '@/store/chatConversationStore';
import type { ServerConversationDetail, ServerConversationSummary } from '@/types/chatConversation';

export function useChatConversations(userId: string | null, ownerKey?: string) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [cursor, setCursor] = useState<string | null>(null);
  const identity = useRef({ userId, ownerKey });
  const busy = useRef(false);
  useEffect(() => {
    identity.current = { userId, ownerKey };
    busy.current = false;
    setLoading(false);
    setError(false);
    setCursor(null);
    return () => { identity.current = { userId: null, ownerKey: undefined }; };
  }, [userId, ownerKey]);

  const current = () => !!userId && !!ownerKey && identity.current.userId === userId &&
    identity.current.ownerKey === ownerKey && useChatConversationStore.getState().identity?.key === ownerKey;

  const list = async (more = false) => {
    if (!current() || busy.current) return;
    busy.current = true;
    setLoading(true);
    setError(false);
    try {
      const query = more && cursor ? `?cursor=${encodeURIComponent(cursor)}` : '';
      const result = await apiChatUserRequest<{ conversations: ServerConversationSummary[]; nextCursor: string | null }>(
        `/api/chat/conversations${query}`, 'GET', userId!,
      );
      if (!current()) return;
      useChatConversationStore.getState().mergeServerRooms(ownerKey!, result.conversations);
      setCursor(result.nextCursor);
    } catch (err) {
      if (current() && !(err instanceof ApiError && err.code === 'persistence_disabled')) setError(true);
    } finally {
      if (current()) { busy.current = false; setLoading(false); }
    }
  };

  const open = async (id: string, reload = false) => {
    const room = useChatConversationStore.getState().conversations[id]?.conversation;
    if (!room || room.ownerKey !== ownerKey) return;
    const refresh = reload || (!!room.serverId && room.notice === 'chat.session.conflict');
    if (!room.serverSummary && !refresh) return id;
    if (!room.serverId || !current() || (!reload && busy.current)) return;
    if (!reload) {
      busy.current = true;
      setLoading(true);
      setError(false);
    }
    try {
      const detail = await apiChatUserRequest<ServerConversationDetail>(
        `/api/chat/conversations/${room.serverId}`, 'GET', userId!,
      );
      if (!current() || detail.conversationId !== room.serverId) return;
      return useChatConversationStore.getState().restoreServerRoom(ownerKey!, detail, refresh ? room.generation : undefined);
    } catch {
      if (!reload && current()) setError(true);
    } finally {
      if (!reload && current()) { busy.current = false; setLoading(false); }
    }
  };
  const older = async (id: string) => {
    if (!current() || busy.current) return;
    const room = useChatConversationStore.getState().conversations[id]?.conversation;
    if (!room?.serverId || !room.olderMessageCursor || room.ownerKey !== ownerKey) return;
    const before = room.olderMessageCursor;
    busy.current = true;
    setLoading(true);
    setError(false);
    try {
      const detail = await apiChatUserRequest<ServerConversationDetail>(
        `/api/chat/conversations/${room.serverId}?cursor=${before}`, 'GET', userId!,
      );
      if (current()) useChatConversationStore.getState().prependServerMessages({ id, ownerKey: ownerKey! }, before, detail);
    } catch {
      if (current()) setError(true);
    } finally {
      if (current()) { busy.current = false; setLoading(false); }
    }
  };
  return { list, open, older, loading, error, hasMore: !!cursor };
}
