import { uuid } from 'expo';
import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, apiChatUserRequest } from '@/lib/api';
import type { ChatMemory, ChatMemoryDecision, ChatMemoryProposal, ChatMemoryProposalGroup, ChatMemoryProposalItem, ChatMemorySettings } from '@/types';

const proposalsPath = '/api/chat/v2/memory-proposals';
const memoriesPath = '/api/chat/memories';
const structuredMemoriesPath = '/api/chat/v2/memories';
const settingsPath = '/api/chat/v2/memory-settings';

export function useChatMemory(userId: string | null, locale: 'en' | 'ko' | 'ja' | 'zh' = 'en') {
  const [memoryState, setMemoryState] = useState<{ owner: string; items: ChatMemory[] }>();
  const [proposalState, setProposalState] = useState<{
    owner: string; conversationId: string; groups: ChatMemoryProposalGroup[];
  }>();
  const [settings, setSettings] = useState<ChatMemorySettings>();
  const [busyOwner, setBusyOwner] = useState<string>();
  const [stateOwner, setStateOwner] = useState(userId);
  const owner = useRef<{ id: string; requests: Map<string, string>; policyVersion?: number } | null>(null);
  const proposalRead = useRef(0);
  const settingsRead = useRef(0);
  const memoryRead = useRef(0);

  if (stateOwner !== userId) {
    setStateOwner(userId);
    setMemoryState(undefined);
    setProposalState(undefined);
    setBusyOwner(undefined);
    setSettings(undefined);
  }

  useEffect(() => {
    owner.current = userId ? { id: userId, requests: new Map() } : null;
    return () => { owner.current = null; };
  }, [userId]);

  const requireOwner = useCallback(() => {
    const binding = owner.current;
    if (!binding || binding.id !== userId) throw new Error('Chat owner changed');
    return binding;
  }, [userId]);

  const requestId = (binding: ReturnType<typeof requireOwner>, key: string) => {
    const id = binding.requests.get(key) ?? uuid.v4();
    binding.requests.set(key, id);
    return id;
  };

  const changeMemories = (binding: ReturnType<typeof requireOwner>, update: (items: ChatMemory[]) => ChatMemory[]) => {
    if (owner.current !== binding) return;
    memoryRead.current++;
    setMemoryState((state) => ({ owner: binding.id, items: update(state?.owner === binding.id ? state.items : []) }));
  };

  const refresh = useCallback(async () => {
    const binding = requireOwner();
    const read = ++memoryRead.current;
    let result: { memories: ChatMemory[] };
    try {
      const path = structuredMemoriesPath + '?locale=' + locale;
      result = await apiChatUserRequest<typeof result>(path, 'GET', binding.id);
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 404) throw error;
      if (owner.current !== binding) throw new Error('Chat owner changed');
      result = await apiChatUserRequest<typeof result>(memoriesPath, 'GET', binding.id);
    }
    if (owner.current === binding && read === memoryRead.current) {
      setMemoryState({ owner: binding.id, items: result.memories });
    }
    return result.memories;
  }, [locale, requireOwner]);

  const refreshSettings = useCallback(async () => {
    const binding = requireOwner();
    const read = ++settingsRead.current;
    let response: ChatMemorySettings | undefined;
    try {
      response = await apiChatUserRequest<ChatMemorySettings>(settingsPath, 'GET', binding.id);
    } catch (error) {
      if (!(error instanceof ApiError) || (error.status !== 404 && error.code !== 'memory_unavailable')) {
        throw error;
      }
    }
    if (owner.current === binding && read === settingsRead.current) {
      setSettings(response);
      const policyChanged = binding.policyVersion !== undefined && binding.policyVersion !== response?.version;
      binding.policyVersion = response?.version;
      if (response?.enabled === false || policyChanged) {
        proposalRead.current++;
        setProposalState(undefined);
      }
      return response;
    }
    return undefined;
  }, [requireOwner]);

  const writeSettings = async (path: string, method: 'PATCH' | 'POST', body: object) => {
    const binding = requireOwner();
    const key = JSON.stringify([path, body]);
    setBusyOwner(binding.id);
    try {
      const result = await apiChatUserRequest<ChatMemorySettings>(path, method, binding.id,
        { ...body, requestId: requestId(binding, key) });
      if (owner.current !== binding) throw new Error('Chat owner changed');
      settingsRead.current++;
      setSettings(result);
      const policyChanged = binding.policyVersion !== undefined && binding.policyVersion !== result.version;
      binding.policyVersion = result.version;
      if (path !== settingsPath) {
        memoryRead.current++;
        setMemoryState(undefined);
      }
      if (path !== settingsPath || result.enabled !== settings?.enabled || policyChanged) {
        proposalRead.current++;
        setProposalState(undefined);
      }
      binding.requests.delete(key);
      return result;
    } finally { if (owner.current === binding) setBusyOwner(undefined); }
  };

  const updateSettings = (current: ChatMemorySettings, enabled?: boolean, acknowledgeNotice?: true) =>
    writeSettings(settingsPath, 'PATCH', { expectedVersion: current.version, enabled, acknowledgeNotice });

  const deleteAll = (current: ChatMemorySettings) => writeSettings(structuredMemoriesPath + '/delete-all', 'POST', {
    expectedVersion: current.version, expectedMemorySetRevision: current.memorySetRevision, confirmed: true,
  });

  const refreshProposals = useCallback(async (conversationId: string) => {
    const binding = requireOwner();
    const read = ++proposalRead.current;
    let groups: ChatMemoryProposalGroup[];
    try {
      groups = await apiChatUserRequest<ChatMemoryProposalGroup[]>(
        proposalsPath + '?conversationId=' + encodeURIComponent(conversationId), 'GET', binding.id,
      );
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 404) throw error;
      groups = [];
    }
    if (owner.current === binding && read === proposalRead.current) {
      setProposalState({ owner: binding.id, conversationId, groups });
    }
  }, [requireOwner]);

  const confirm = async (proposal: ChatMemoryProposal) => {
    const binding = requireOwner();
    const key = 'create:' + proposal.proposalId + ':' + proposal.version;
    setBusyOwner(binding.id);
    try {
      const result = await apiChatUserRequest<{ memoryId: string; memoryVersion: number }>(
        memoriesPath, 'POST', binding.id,
        { requestId: requestId(binding, key), proposalId: proposal.proposalId,
          expectedProposalVersion: proposal.version, confirmed: true },
      );
      changeMemories(binding, (items) => [
        ...items.filter((item) => item.id !== result.memoryId),
        { id: result.memoryId, kind: proposal.kind, value: proposal.value,
          version: result.memoryVersion, consentScope: proposal.consentScope },
      ]);
      binding.requests.delete(key);
      return result;
    } finally { if (owner.current === binding) setBusyOwner(undefined); }
  };

  const update = async (memory: ChatMemory, value: string) => {
    const binding = requireOwner();
    const key = 'update:' + memory.id + ':' + memory.version + ':' + value;
    setBusyOwner(binding.id);
    try {
      const body = { requestId: requestId(binding, key), expectedVersion: memory.version, confirmed: true, value };
      if (memory.schemaVersion === 2) {
        const result = await apiChatUserRequest<ChatMemory>(
          structuredMemoriesPath + '/' + memory.id, 'PATCH', binding.id, { ...body, locale },
        );
        changeMemories(binding, (items) => items.map((item) => item.id === memory.id ? result : item));
      } else {
        const result = await apiChatUserRequest<{ memoryVersion: number }>(
          memoriesPath + '/' + memory.id, 'PATCH', binding.id, body,
        );
        changeMemories(binding, (items) => items.map((item) => item.id === memory.id
          ? { ...item, value: value.trim(), version: result.memoryVersion } : item));
      }
      binding.requests.delete(key);
    } finally { if (owner.current === binding) setBusyOwner(undefined); }
  };

  const remove = async (memory: ChatMemory) => {
    const binding = requireOwner();
    const key = 'delete:' + memory.id;
    setBusyOwner(binding.id);
    try {
      const path = memory.schemaVersion === 2 ? structuredMemoriesPath : memoriesPath;
      await apiChatUserRequest(path + '/' + memory.id, 'DELETE', binding.id, undefined,
        { 'Idempotency-Key': requestId(binding, key) });
      changeMemories(binding, (items) => items.filter((item) => item.id !== memory.id));
      binding.requests.delete(key);
    } finally { if (owner.current === binding) setBusyOwner(undefined); }
  };

  const editProposal = async (group: ChatMemoryProposalGroup, item: ChatMemoryProposalItem, value: string) => {
    const binding = requireOwner();
    const key = JSON.stringify(['edit', group.groupId, item.itemId, item.version, value]);
    setBusyOwner(binding.id);
    try {
      const edited = await apiChatUserRequest<ChatMemoryProposalItem>(
        proposalsPath + '/' + group.groupId + '/' + item.itemId, 'PATCH', binding.id,
        { requestId: requestId(binding, key), expectedVersion: item.version, value },
      );
      if (owner.current !== binding) throw new Error('Chat owner changed');
      proposalRead.current++;
      setProposalState((state) => {
        if (state?.owner !== binding.id || state.conversationId !== group.conversationId) return state;
        return { ...state, groups: state.groups.map((entry) => entry.groupId !== group.groupId ? entry
          : { ...entry, items: entry.items.map((candidate) => candidate.itemId === item.itemId ? edited : candidate) }) };
      });
      binding.requests.delete(key);
    } finally { if (owner.current === binding) setBusyOwner(undefined); }
  };

  const decideProposals = async (group: ChatMemoryProposalGroup, decisions: ChatMemoryDecision[]) => {
    const binding = requireOwner();
    const key = JSON.stringify(['decide', group.groupId, decisions]);
    setBusyOwner(binding.id);
    try {
      const result = await apiChatUserRequest<{
        items: { itemId: string; status: 'approved' | 'rejected' | 'deferred' }[];
      }>(proposalsPath + '/' + group.groupId + '/decisions', 'POST', binding.id,
        { requestId: requestId(binding, key), decisions });
      if (owner.current !== binding) throw new Error('Chat owner changed');
      proposalRead.current++;
      const statuses = new Map(result.items.map((item) => [item.itemId, item.status]));
      setProposalState((state) => {
        if (state?.owner !== binding.id || state.conversationId !== group.conversationId) return state;
        return { ...state, groups: state.groups.map((entry) => entry.groupId !== group.groupId ? entry
          : { ...entry, items: entry.items.flatMap((item) => {
            const status = statuses.get(item.itemId);
            if (status === 'approved' || status === 'rejected') return [];
            return [status === 'deferred' ? { ...item, status } : item];
          }) }).filter((entry) => entry.items.length > 0) };
      });
      binding.requests.delete(key);
      return result;
    } finally { if (owner.current === binding) setBusyOwner(undefined); }
  };

  return {
    memories: memoryState?.owner === userId ? memoryState.items : [],
    settings: stateOwner === userId ? settings : undefined,
    proposalState: proposalState?.owner === userId ? proposalState : undefined,
    busy: busyOwner === userId, refresh, confirm, update, remove,
    refreshSettings, updateSettings, deleteAll, refreshProposals, editProposal, decideProposals,
  };
}
