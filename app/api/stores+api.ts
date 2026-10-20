import { listStores } from '@/server/catalog';
import { json } from '@/server/http';

export function GET() {
  return json({ stores: listStores() }, { maxAgeSeconds: 3600 });
}
