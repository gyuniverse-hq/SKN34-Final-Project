import { json } from '@/server/http';
import { isNaverConfigured } from '@/server/naver';
import { isYoutubeConfigured } from '@/server/youtube';

export function GET() {
  return json({
    ok: true,
    integrations: { youtube: isYoutubeConfigured(), naverShopping: isNaverConfigured() },
  });
}
