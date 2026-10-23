/** Development-only gateway. No client receives the local service token. */
import { errorResponse } from '@/server/lib/http';

const GET_ACTIONS = new Set(['status', 'job', 'export', 'sample']);
const POST_ACTIONS = new Set(['load', 'infer', 'evaluate', 'profile']);
const MAX_BYTES = 18 * 1024 * 1024;

export async function niaProxy(request: Request, action: string) {
  // NODE_ENV must explicitly be development: tests, builds and production fail closed.
  if (process.env.NODE_ENV !== 'development') {
    return errorResponse(404, 'Not found', 'not_found');
  }
  const allowed = request.method === 'GET' ? GET_ACTIONS : request.method === 'POST' ? POST_ACTIONS : undefined;
  if (!allowed?.has(action)) {
    return errorResponse(404, 'Not found', 'not_found');
  }
  const token = process.env.NIA_EVAL_TOKEN;
  const port = process.env.NIA_EVAL_PORT || '8765';
  if (!token || token.length < 32 || !/^\d{1,5}$/.test(port)) {
    return errorResponse(503, 'Configure the local NIA evaluation service (reports/skin-analysis/nia-evaluation.md)', 'nia_unavailable');
  }
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 120_000);
  try {
    const url = new URL(request.url);
    const target = new URL(`http://127.0.0.1:${port}/${action}`);
    for (const name of ['id', 'format', 'index']) {
      const value = url.searchParams.get(name);
      if (value !== null) target.searchParams.set(name, value);
    }
    let body: string | undefined;
    if (request.method === 'POST') {
      // Stream with a hard cap; do not trust Content-Length from an uploading client.
      const reader = request.body?.getReader();
      if (!reader) return errorResponse(400, 'JSON body required', 'invalid_request');
      const chunks: Uint8Array[] = [];
      let size = 0;
      while (true) {
        const chunk = await reader.read();
        if (chunk.done) break;
        size += chunk.value.byteLength;
        if (size > MAX_BYTES) {
          await reader.cancel();
          return errorResponse(413, 'Image upload exceeds 18 MiB', 'upload_limit');
        }
        chunks.push(chunk.value);
      }
      const bytes = new Uint8Array(size);
      let offset = 0;
      for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
      body = new TextDecoder().decode(bytes);
    }
    const response = await fetch(target, {
      method: request.method, body, signal: controller.signal,
      headers: { 'X-NIA-Token': token, 'Content-Type': 'application/json' },
    });
    return new Response(await response.text(), {
      status: response.status,
      headers: {
        'Content-Type': response.headers.get('Content-Type') || 'application/json',
        'Cache-Control': 'no-store',
        ...(action === 'export' ? { 'Content-Disposition': `attachment; filename="nia-evaluation.${target.searchParams.get('format') === 'csv' ? 'csv' : 'json'}"` } : {}),
      },
    });
  } catch {
    return errorResponse(503, 'Local NIA service is unavailable or timed out (reports/skin-analysis/nia-evaluation.md)', 'nia_unavailable');
  } finally {
    clearTimeout(timeout);
  }
}
