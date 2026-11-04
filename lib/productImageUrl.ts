/** Collected Olive Young thumbs used `thumbnails10/` (no slash). The CDN now serves `thumbnails/10/`. */
const GLUED_THUMB = /^(https:\/\/image\.oliveyoung\.co\.kr\/cfimages\/cf-goods\/uploads\/images\/)thumbnails(\d+)\//;

/** URL the app can load. Empty stays empty (ProductImage shows the placeholder). */
export function publicProductImageUrl(url: string | undefined): string {
  if (!url) return '';
  return url.replace(GLUED_THUMB, '$1thumbnails/$2/');
}
