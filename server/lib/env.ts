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
  // Public values shared with the app, used here only to verify access tokens.
  get supabaseUrl() {
    return process.env.SUPABASE_URL || process.env.EXPO_PUBLIC_SUPABASE_URL || undefined;
  },
  get supabasePublishableKey() {
    return process.env.SUPABASE_PUBLISHABLE_KEY || process.env.EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY || undefined;
  },
};
