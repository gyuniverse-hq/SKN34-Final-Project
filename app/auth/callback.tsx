import * as Linking from 'expo-linking';
import { useRouter } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { useEffect } from 'react';
import { LoadingState } from '@/components/ui/StateViews';
import { completeAuthRedirect } from '@/lib/auth';

// On web this page loads inside the sign-in popup and hands the URL back to the opener.
if (typeof window !== 'undefined') WebBrowser.maybeCompleteAuthSession();

export default function AuthCallbackScreen() {
  const router = useRouter();
  const url = Linking.useLinkingURL();

  useEffect(() => {
    if (!url) return;
    completeAuthRedirect(url)
      .catch(() => {})
      .finally(() => router.dismissTo('/my'));
  }, [url, router]);

  return <LoadingState />;
}
