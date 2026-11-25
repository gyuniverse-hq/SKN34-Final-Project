import AsyncStorage from '@react-native-async-storage/async-storage';
import { useQueryClient, type QueryClient, type QueryKey } from '@tanstack/react-query';
import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { deleteAccount, hasAccountDeletionFence } from '@/lib/account';
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
  issue?: Issue;
};

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
    const restore = (pending: boolean) => {
      if (active) {
        setState(previous => previous?.owner === owner
          ? previous
          : { owner, phase: pending ? 'pending' : 'ready' });
      }
    };
    void AsyncStorage.getItem(markerKey(owner)).then(value => restore(value === '1'), () => restore(false));
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

  const prepare = useCallback((id: string) => {
    const existing = preparation.current.get(id);
    if (existing) return existing;
    const tasks = Promise.allSettled([
      AsyncStorage.setItem(markerKey(id), '1'),
      clearAccountData(client, id),
    ]);
    preparation.current.set(id, tasks);
    return tasks;
  }, [client]);

  useEffect(() => {
    if (owner && (serverFence || phase === 'pending')) void prepare(owner);
  }, [owner, phase, prepare, serverFence]);

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

      if (result === 'pending') {
        if (activeOwner.current === id) {
          setState({ owner: id, phase: 'pending' });
        }
        await prepare(id);
        return;
      }

      setState(previous => previous?.owner === id ? { owner: id, phase: 'complete' } : previous);
      await finish(id);
    });
  }

  const visible = owner ? owned : state;
  const issue = owner || visible?.phase === 'complete' ? visible?.issue : 'sessionEnded';
  const progress = visible?.phase === 'complete' ? 'complete'
    : serverFence || visible?.phase === 'pending' ? 'pending' : undefined;
  const busy = !!visible && running.has(visible.owner);

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
    } else if (owner && issue !== 'sessionEnded') {
      await submit(owner);
    }
  }

  return {
    busy, waiting, progress, issue, signedIn: !!owner, submit, check, leave,
  };
}

export const AccountDeletionContext = createContext<ReturnType<typeof useAccountDeletionController> | null>(null);

export function useAccountDeletion() {
  const deletion = useContext(AccountDeletionContext);
  if (!deletion) throw new Error('Account deletion requires its root controller');
  return deletion;
}
