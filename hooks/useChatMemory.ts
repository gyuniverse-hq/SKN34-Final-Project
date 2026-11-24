import { uuid } from 'expo';
import { useEffect, useRef, useState } from 'react';
import { apiChatUserRequest } from '@/lib/api';
import type { ChatMemory, ChatMemoryProposal } from '@/types';

export function useChatMemory(userId: string | null) {
  const [memories, setMemories] = useState<ChatMemory[]>([]);
  const [busy, setBusy] = useState(false);
  const pendingIds = useRef(new Map<string, string>());
  const owner = useRef(userId);
  useEffect(() => {
    owner.current = userId;
    pendingIds.current.clear();
    setMemories([]);
    setBusy(false);
    return () => { owner.current = null; pendingIds.current.clear(); };
  }, [userId]);

  const requireOwner = () => {
    if (!userId || owner.current !== userId) throw new Error('Chat owner changed');
    return userId;
  };
  const requestId = (key: string) => {
    const value = pendingIds.current.get(key) ?? uuid.v4();
    pendingIds.current.set(key, value);
    return value;
  };
  const refresh = async () => {
    const id = requireOwner();
    const result = await apiChatUserRequest<{ memories: ChatMemory[] }>('/api/chat/memories', 'GET', id);
    if (owner.current === id) setMemories(result.memories);
    return result.memories;
  };
  const confirm = async (proposal: ChatMemoryProposal) => {
    const id = requireOwner();
    const key = `create:${proposal.proposalId}:${proposal.version}`;
    setBusy(true);
    try {
      const result = await apiChatUserRequest<{ memoryId: string; memoryVersion: number }>(
        '/api/chat/memories', 'POST', id,
        { requestId: requestId(key), proposalId: proposal.proposalId,
          expectedProposalVersion: proposal.version, confirmed: true },
      );
      if (owner.current === id) setMemories((items) => [
        ...items.filter((item) => item.id !== result.memoryId),
        { id: result.memoryId, kind: proposal.kind, value: proposal.value,
          version: result.memoryVersion, consentScope: proposal.consentScope },
      ]);
      pendingIds.current.delete(key);
      return result;
    } finally { if (owner.current === id) setBusy(false); }
  };
  const update = async (memory: ChatMemory, value: string) => {
    const id = requireOwner();
    const key = `update:${memory.id}:${memory.version}:${value}`;
    setBusy(true);
    try {
      const result = await apiChatUserRequest<{ memoryVersion: number }>(`/api/chat/memories/${memory.id}`, 'PATCH', id,
        { requestId: requestId(key), expectedVersion: memory.version, confirmed: true, value });
      if (owner.current === id) setMemories((items) => items.map((item) => item.id === memory.id
        ? { ...item, value: value.trim(), version: result.memoryVersion } : item));
      pendingIds.current.delete(key);
    } finally { if (owner.current === id) setBusy(false); }
  };
  const remove = async (memory: ChatMemory) => {
    const id = requireOwner();
    const key = `delete:${memory.id}`;
    setBusy(true);
    try {
      await apiChatUserRequest(`/api/chat/memories/${memory.id}`, 'DELETE', id, undefined,
        { 'Idempotency-Key': requestId(key) });
      if (owner.current === id) setMemories((items) => items.filter((item) => item.id !== memory.id));
      pendingIds.current.delete(key);
    } finally { if (owner.current === id) setBusy(false); }
  };
  return { memories, busy, refresh, confirm, update, remove };
}
