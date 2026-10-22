import { json } from '@/server/lib/http';
import { getIntegrationStatus } from '@/server/services/integrationService';

export function GET() {
  return json({ ok: true, integrations: getIntegrationStatus() });
}
