import { listLooks } from '@/server/catalog';
import { json } from '@/server/http';

export function GET() {
  return json({ looks: listLooks() }, { maxAgeSeconds: 300 });
}
