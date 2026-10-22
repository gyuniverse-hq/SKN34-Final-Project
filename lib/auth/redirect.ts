export type AuthRedirect =
  | { type: 'session'; accessToken: string; refreshToken: string }
  | { type: 'error'; message: string }
  | { type: 'none' };

function parseParams(part: string, into: Map<string, string>) {
  for (const pair of part.split('&')) {
    if (!pair) continue;
    const index = pair.indexOf('=');
    const key = index === -1 ? pair : pair.slice(0, index);
    const value = index === -1 ? '' : pair.slice(index + 1);
    into.set(decodeURIComponent(key), decodeURIComponent(value.replace(/\+/g, ' ')));
  }
}

/** Reads the session or error Supabase appends to the OAuth redirect URL (query or fragment). */
export function parseAuthRedirect(url: string): AuthRedirect {
  const hashIndex = url.indexOf('#');
  const beforeHash = hashIndex === -1 ? url : url.slice(0, hashIndex);
  const queryIndex = beforeHash.indexOf('?');
  const params = new Map<string, string>();
  if (queryIndex !== -1) parseParams(beforeHash.slice(queryIndex + 1), params);
  if (hashIndex !== -1) parseParams(url.slice(hashIndex + 1), params);

  const error = params.get('error_description') || params.get('error');
  if (error) return { type: 'error', message: error };
  const accessToken = params.get('access_token');
  const refreshToken = params.get('refresh_token');
  if (accessToken && refreshToken) return { type: 'session', accessToken, refreshToken };
  return { type: 'none' };
}
