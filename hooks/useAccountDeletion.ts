import AsyncStorage from '@react-native-async-storage/async-storage';
import { useQueryClient, type QueryClient, type QueryKey } from '@tanstack/react-query';
import { createContext, useCallback, useContext, useEffect, useEffectEvent, useLayoutEffect, useRef, useState } from 'react';
import { accountDeletionStatus, deleteAccount, hasAccountDeletionFence, isAccountDeletionReceipt } from '@/lib/account';
import { ApiError } from '@/lib/api';
import { getCurrentUserId, signOut, useAuth } from '@/lib/auth';
import { useMe } from '@/lib/queries';
import { skinProfileKey } from '@/lib/skinProfile';
import { pendingProfileKey } from '@/lib/skinRegistration';
import { chatRequestRecoveryPrefix, chatRoomDeletionPrefix, STORAGE_KEYS } from '@/lib/storage';
import { useChatConversationStore } from '@/store/chatConversationStore';
import { useSkinProfileStore } from '@/store/skinProfileStore';

type Issue = 'unconfirmed' | 'sessionEnded' | 'cleanupFailed' | 'signOutFailed';
type DeletionState = {
  owner: string;
  phase: 'ready' | 'pending' | 'complete';
  receipt?: string;
  issue?: Issue;
};

const STATUS_POLL_MS = 2_000;

const markerKey = (owner: string) => `${STORAGE_KEYS.accountDeletion}:${owner}`;

function ownsQuery(key: QueryKey, owner: string) {
  return ((key[0] === 'me' || key[0] === 'skin-access') && key[1] === owner) ||
    (key[0] === 'skincare-recommendations' && key[1] === 'v4' && key[2] === owner);
}

async function clearAccountData(client: QueryClient, owner: string) {
  const chat = useChatConversationStore.getState();
  if (chat.identity?.userId === owner) chat.activate(null);
  const skin = useSkinProfileStore.getState();
  if (skin.owner === owner) skin.reset();

  const filters = { predicate: ({ queryKey }: { queryKey: QueryKey }) => ownsQuery(queryKey, owner) };
  await client.cancelQueries(filters);
  client.removeQueries(filters);
  const deletionPrefix = chatRoomDeletionPrefix(owner);
  const recoveryPrefix = chatRequestRecoveryPrefix(owner);
  const chatKeys = (await AsyncStorage.getAllKeys()).filter(key => key.startsWith(deletionPrefix) || key.startsWith(recoveryPrefix));
  await AsyncStorage.multiRemove([
    skinProfileKey(owner),
    pendingProfileKey(owner),
    `${STORAGE_KEYS.firstArInvitation}:${owner}`,
    ...chatKeys,
  ]);
}

async function signOutOwner(owner: string, maySignOut: () => boolean) {
  if (!maySignOut() || await getCurrentUserId() !== owner || !maySignOut()) return;
  try {
    await signOut();
  } catch (error) {
    // The SDK can report a remote logout error after clearing the local session.
    if (await getCurrentUserId() === owner) throw error;
  }
}

export function useAccountDeletionController() {
  const { user, ready } = useAuth();
  const owner = user?.id ?? null;
  const client = useQueryClient();
  const [state, setState] = useState<DeletionState>();
  const [running, setRunning] = useState<ReadonlySet<string>>(() => new Set());
  const activeOwner = useRef(owner);
  const operations = useRef(new Set<string>());
  const preparation = useRef(new Map<string, Promise<unknown>>());
  const owned = state?.owner === owner ? state : undefined;
  const me = useMe(ready && owned?.phase === 'ready' ? owned.owner : undefined);
  const serverFence = hasAccountDeletionFence(me.error);
  const waiting = !ready || (!!owner && !owned);

  useLayoutEffect(() => {
    activeOwner.current = owner;
    if (owner) {
      setState(previous => previous?.owner === owner ? previous : undefined);
    }
    return () => { activeOwner.current = null; };
  }, [owner]);

  useEffect(() => {
    if (!ready || !owner) return;
    let active = true;
    const restore = (marker: string | null) => {
      if (active) {
        const receipt = isAccountDeletionReceipt(marker) ? marker : undefined;
        setState(previous => previous?.owner === owner
          ? previous
          : { owner, phase: marker === '1' || receipt ? 'pending' : 'ready', receipt });
      }
    };
    void AsyncStorage.getItem(markerKey(owner)).then(restore, () => restore(null));
    return () => { active = false; };
  }, [owner, ready]);

  const phase = owned?.phase;
  useEffect(() => {
    if (owner && serverFence && phase === 'ready') {
      setState(previous => previous?.owner === owner && previous.phase === 'ready'
        ? { owner, phase: 'pending' }
        : previous);
    }
  }, [owner, serverFence, phase]);

  const prepare = useCallback((id: string, receipt?: string) => {
    const existing = preparation.current.get(id);
    if (existing) return existing;
    const tasks = Promise.allSettled([
      AsyncStorage.setItem(markerKey(id), receipt ?? '1'),
      clearAccountData(client, id),
    ]);
    preparation.current.set(id, tasks);
    return tasks;
  }, [client]);

  useEffect(() => {
    if (owner && (serverFence || phase === 'pending')) void prepare(owner, owned?.receipt);
  }, [owner, owned?.receipt, phase, prepare, serverFence]);

  async function runOnce(id: string, action: () => Promise<void>) {
    if (operations.current.has(id)) return;
    operations.current.add(id);
    setRunning(new Set(operations.current));
    try {
      await action();
    } finally {
      operations.current.delete(id);
      setRunning(new Set(operations.current));
    }
  }

  function setIssue(id: string, issue?: Issue) {
    setState(previous => previous?.owner === id ? { ...previous, issue } : previous);
  }

  async function finish(id: string) {
    setIssue(id);
    try {
      await preparation.current.get(id);
      await clearAccountData(client, id);
      await signOutOwner(id, () => activeOwner.current === id);
      await AsyncStorage.removeItem(markerKey(id));
      preparation.current.delete(id);
    } catch {
      setIssue(id, 'cleanupFailed');
    }
  }

  async function submit(id: string) {
    if (activeOwner.current !== id) return;
    await runOnce(id, async () => {
      setIssue(id);
      let result: Awaited<ReturnType<typeof deleteAccount>>;
      try {
        result = await deleteAccount(id);
      } catch (error) {
        if (activeOwner.current !== id) return;
        setIssue(id, error instanceof ApiError && error.status === 401 ? 'sessionEnded' : 'unconfirmed');
        return;
      }

      if (result.phase === 'pending') {
        if (activeOwner.current === id || (activeOwner.current === null && result.receipt)) {
          setState(previous => previous?.owner === id
            ? { owner: id, phase: 'pending', receipt: result.receipt } : previous);
        }
        await prepare(id, result.receipt);
        if (result.receipt) await AsyncStorage.setItem(markerKey(id), result.receipt).catch(() => {});
        return;
      }

      setState(previous => previous?.owner === id ? { owner: id, phase: 'complete' } : previous);
      await finish(id);
    });
  }

  const visible = owner ? owned : state;
  const issue = owner || visible?.receipt || visible?.phase === 'complete' ? visible?.issue : 'sessionEnded';
  const progress = visible?.phase === 'complete' ? 'complete'
    : serverFence || visible?.phase === 'pending' ? 'pending' : undefined;
  const busy = !!visible && running.has(visible.owner);
  const pendingReceipt = progress === 'pending' ? visible?.receipt : undefined;
  const pendingOwner = pendingReceipt ? visible?.owner : undefined;

  async function checkReceipt(id: string, receipt: string) {
    if (activeOwner.current !== null && activeOwner.current !== id) return;
    await runOnce(id, async () => {
      setIssue(id);
      try {
        if (await accountDeletionStatus(receipt) !== 'complete') return;
        if (activeOwner.current !== null && activeOwner.current !== id) return;
        await finish(id);
        setState(previous => previous?.owner === id && previous.receipt === receipt
          ? { owner: id, phase: 'complete', issue: previous.issue } : previous);
      } catch {
        setIssue(id, 'unconfirmed');
      }
    });
  }

  const poll = useEffectEvent(checkReceipt);
  useEffect(() => {
    if (!ready || !pendingOwner || !pendingReceipt || issue) return;
    const timer = setInterval(() => { void poll(pendingOwner, pendingReceipt); }, STATUS_POLL_MS);
    return () => clearInterval(timer);
  }, [ready, pendingOwner, pendingReceipt, issue]);

  async function leave() {
    if (!visible) return;
    const id = visible.owner;
    if (!owner) {
      setState(undefined);
      return;
    }
    if (owner !== id || activeOwner.current !== id) return;
    await runOnce(id, async () => {
      try {
        await signOutOwner(id, () => activeOwner.current === id);
        setState(previous => previous?.owner === id ? undefined : previous);
      } catch {
        setIssue(id, 'signOutFailed');
      }
    });
  }

  async function check() {
    if (!visible) return;
    if (progress === 'complete') {
      await runOnce(visible.owner, () => finish(visible.owner));
    } else if (visible.receipt) {
      await checkReceipt(visible.owner, visible.receipt);
    } else if (owner && issue !== 'sessionEnded') {
      await submit(owner);
    }
  }

  return {
    busy, waiting, progress, issue, signedIn: !!owner, canCheck: !!owner || !!pendingReceipt, submit, check, leave,
  };
}

export const AccountDeletionContext = createContext<ReturnType<typeof useAccountDeletionController> | null>(null);

export function useAccountDeletion() {
  const deletion = useContext(AccountDeletionContext);
  if (!deletion) throw new Error('Account deletion requires its root controller');
  return deletion;
}
