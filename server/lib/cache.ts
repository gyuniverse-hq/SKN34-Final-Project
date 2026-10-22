interface Entry<T> {
  value: T;
  expiresAt: number;
}

/**
 * Small in-memory TTL cache with in-flight request de-duplication.
 * Per server instance only — good enough to protect third-party API quotas.
 */
export class TtlCache<T> {
  private store = new Map<string, Entry<T>>();
  private inflight = new Map<string, Promise<T>>();

  constructor(
    private ttlMs: number,
    private maxEntries = 500
  ) {}

  async getOrLoad(key: string, load: () => Promise<T>): Promise<T> {
    const hit = this.store.get(key);
    if (hit && hit.expiresAt > Date.now()) return hit.value;

    const pending = this.inflight.get(key);
    if (pending) return pending;

    const promise = load()
      .then((value) => {
        this.set(key, value);
        return value;
      })
      .finally(() => this.inflight.delete(key));
    this.inflight.set(key, promise);
    return promise;
  }

  set(key: string, value: T) {
    if (this.store.size >= this.maxEntries) {
      const oldest = this.store.keys().next().value;
      if (oldest !== undefined) this.store.delete(oldest);
    }
    this.store.set(key, { value, expiresAt: Date.now() + this.ttlMs });
  }
}

/** Fixed-window rate limiter keyed by client identifier. */
export class RateLimiter {
  private hits = new Map<string, { count: number; windowStart: number }>();

  constructor(
    private limit: number,
    private windowMs: number
  ) {}

  allow(key: string): boolean {
    const now = Date.now();
    const entry = this.hits.get(key);
    if (!entry || now - entry.windowStart >= this.windowMs) {
      if (this.hits.size > 5000) this.hits.clear();
      this.hits.set(key, { count: 1, windowStart: now });
      return true;
    }
    entry.count += 1;
    return entry.count <= this.limit;
  }
}
