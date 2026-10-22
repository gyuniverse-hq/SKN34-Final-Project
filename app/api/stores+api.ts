import { json } from '@/server/lib/http';
import { listStores } from '@/server/services/catalogService';

export async function GET() {
  return json({ stores: await listStores() }, { maxAgeSeconds: 3600 });
}
