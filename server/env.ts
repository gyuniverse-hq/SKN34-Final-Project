/** Server-only configuration. Never import this from client code. */
export const serverEnv = {
  get youtubeApiKey() {
    return process.env.YOUTUBE_API_KEY || undefined;
  },
  get naverClientId() {
    return process.env.NAVER_CLIENT_ID || undefined;
  },
  get naverClientSecret() {
    return process.env.NAVER_CLIENT_SECRET || undefined;
  },
};
