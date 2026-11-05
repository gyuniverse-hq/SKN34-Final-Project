import { niaProxy } from '@/server/services/niaEvaluationService';

export function GET(request: Request, { action }: Record<string, string>) {
  return niaProxy(request, action);
}

export function POST(request: Request, { action }: Record<string, string>) {
  return niaProxy(request, action);
}
