import { json } from '@/server/lib/http';
import { listLooks } from '@/server/services/catalogService';

export async function GET() {
  return json({ looks: await listLooks() }, { maxAgeSeconds: 300 });
}
