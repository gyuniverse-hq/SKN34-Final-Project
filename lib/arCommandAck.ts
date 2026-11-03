import { apiPostOwned, type ArRequestOwner } from '@/lib/api';
import type { ArOutcome } from '@/store/makeupStore';

export type ArAck = ArOutcome & { requestId: string; commandId: string; sessionId: string };

// Development-only outbox: retained while the JS process lives, never re-executes a command.
const outbox = new Map<string, { body: ArAck; owner: ArRequestOwner }>();
const inflight = new Map<string, Promise<void>>();
const listeners = new Set<() => void>();
const notify = () => listeners.forEach((listener) => listener());

export function subscribeArAcks(listener: () => void) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export function pendingArAcks() { return outbox.size; }

export async function retryArAcks() {
  await Promise.all([...outbox.keys()].map(sendAck));
}

async function sendAck(commandId: string): Promise<void> {
  const existing = inflight.get(commandId);
  if (existing) return existing;
  const entry = outbox.get(commandId);
  if (!entry) return;
  const attempt = (async () => {
    try {
      const response = await apiPostOwned<{ received?: boolean }>('/api/chat/acks', entry.body, {
        expectedOwner: entry.owner,
      });
      if (response.data?.received === true) outbox.delete(commandId);
    } catch {
      // Keep the exact same ACK for a later retry; never issue the command again.
    } finally {
      inflight.delete(commandId);
      notify();
    }
  })();
  inflight.set(commandId, attempt);
  return attempt;
}

export function queueArAck(body: ArAck, owner: ArRequestOwner) {
  if (outbox.has(body.commandId)) return;
  outbox.set(body.commandId, { body: { ...body }, owner: { ...owner } });
  notify();
  void sendAck(body.commandId);
}
