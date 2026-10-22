import { getAuthUser, isAuthConfigured } from '@/server/lib/auth';
import { errorResponse, json } from '@/server/lib/http';
import type { MeResponse } from '@/types';

export async function GET(request: Request) {
  if (!isAuthConfigured()) return errorResponse(503, 'Login is not configured', 'auth_unavailable');
  const user = await getAuthUser(request);
  if (!user) return errorResponse(401, 'Sign in required', 'unauthorized');
  return json<MeResponse>({ user });
}
