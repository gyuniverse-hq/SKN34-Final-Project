import { isNaverConfigured } from '@/server/clients/naverClient';
import { isYoutubeConfigured } from '@/server/clients/youtubeClient';

export function getIntegrationStatus() {
  return { youtube: isYoutubeConfigured(), naverShopping: isNaverConfigured() };
}
