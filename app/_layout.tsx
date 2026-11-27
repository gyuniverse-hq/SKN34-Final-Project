import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useFonts } from 'expo-font';
import { Stack } from 'expo-router';
import Head from 'expo-router/head';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { useEffect, useState, useSyncExternalStore } from 'react';
import { ActivityIndicator, View } from 'react-native';
import { AccountDeletionProgress } from '@/components/account/AccountDeletionProgress';
import { theme } from '@/constants/theme';
import { AccountDeletionContext, useAccountDeletionController } from '@/hooks/useAccountDeletion';
import { useTermsConsentGate } from '@/hooks/useTermsConsent';
import { ApiError } from '@/lib/api';
import { useI18n } from '@/lib/i18n';

export { ErrorBoundary } from 'expo-router';

export const unstable_settings = {
  anchor: '(tabs)',
};

SplashScreen.preventAutoHideAsync().catch(() => {});

function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 5 * 60 * 1000,
        retry: (failureCount, error) =>
          !(error instanceof ApiError && error.status >= 400 && error.status < 500) && failureCount < 2,
      },
    },
  });
}

export default function RootLayout() {
  const [queryClient] = useState(createQueryClient);
  const [fontsLoaded, fontError] = useFonts({
    [theme.fontFamily.regular]: require('@/assets/fonts/NanumGothic-Regular.ttf'),
    [theme.fontFamily.display]: require('@/assets/fonts/NanumGothic-Bold.ttf'),
  });

  useEffect(() => {
    if (fontsLoaded || fontError) SplashScreen.hideAsync().catch(() => {});
  }, [fontsLoaded, fontError]);

  if (!fontsLoaded && !fontError) return null;
  return (
    <QueryClientProvider client={queryClient}>
      <Head>
        <title>VISHUE</title>
      </Head>
      <StatusBar style="dark" />
      <AccountDeletionGate />
    </QueryClientProvider>
  );
}

function AccountDeletionGate() {
  const deletion = useAccountDeletionController();
  // Keep the initial web render consistent with the server's signed-out HTML.
  const hydrated = useSyncExternalStore(subscribeToHydration, () => true, () => false);
  const waiting = hydrated && deletion.waiting;
  if (deletion.progress) {
    return <AccountDeletionProgress complete={deletion.progress === 'complete'}
      busy={deletion.busy} issue={deletion.issue} signedIn={deletion.signedIn} canCheck={deletion.canCheck}
      onCheck={() => { void deletion.check(); }} onLeave={() => { void deletion.leave(); }} />;
  }
  return <AccountDeletionContext.Provider value={deletion}>
    {waiting && <View style={{ flex: 1, justifyContent: 'center', backgroundColor: theme.colors.surface }}>
      <ActivityIndicator />
    </View>}
    {/* Preserve the initial route while the account's local receipt is loading. */}
    <View style={{ flex: 1, display: waiting ? 'none' : 'flex' }}>
      {!waiting && <TermsConsentGate />}
      <RootStack />
    </View>
  </AccountDeletionContext.Provider>;
}

const subscribeToHydration = () => () => {};

function TermsConsentGate() {
  useTermsConsentGate();
  return null;
}

function RootStack() {
  const { t } = useI18n();
  return (
    <Stack
      screenOptions={{
        headerStyle: { backgroundColor: theme.colors.surface },
        headerTintColor: theme.colors.ink,
        headerTitleStyle: { fontWeight: '700' },
        headerShadowVisible: false,
        headerBackButtonDisplayMode: 'minimal',
        contentStyle: { backgroundColor: theme.colors.surface },
      }}>
      <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
      <Stack.Screen name="community-write" options={{ title: t('community.write') }} />
      <Stack.Screen name="community-post" options={{ title: t('community.heading') }} />
      <Stack.Screen name="community-mine" options={{ title: t('community.mine') }} />
      <Stack.Screen name="chat" options={{ title: t('chat.title') }} />
      <Stack.Screen name="style-browse" options={{ title: t('tabs.looks') }} />
      <Stack.Screen name="product/[id]" options={{ title: '' }} />
      <Stack.Screen name="look/[id]" options={{ title: '' }} />
      <Stack.Screen name="idol-looks" options={{ title: '' }} />
      <Stack.Screen name="idol-look/[id]" options={{ title: '' }} />
      <Stack.Screen name="celebrities/index" options={{ title: '' }} />
      <Stack.Screen name="celebrities/[id]" options={{ title: '' }} />
      <Stack.Screen name="celebrity-video/[id]" options={{ title: '' }} />
      <Stack.Screen name="look-preview" options={{ title: '' }} />
      <Stack.Screen name="search" options={{ title: t('search.title') }} />
      <Stack.Screen name="discover" options={{ title: t('search.title') }} />
      <Stack.Screen name="rankings" options={{ title: t('discovery.ranking') }} />
      <Stack.Screen name="compare" options={{ title: t('compare.title') }} />
      <Stack.Screen name="recommendations" options={{ title: t('rec.title') }} />
      <Stack.Screen name="external-link" options={{ title: t('ext.screenTitle'), presentation: 'modal' }} />
      <Stack.Screen name="skin-consent" options={{ title: t('skinFlow.consent.screenTitle') }} />
      <Stack.Screen name="skin-recommendations" options={{ title: t('skinFlow.resultTitle') }} />
      <Stack.Screen name="cart" options={{ title: t('cart.title') }} />
      <Stack.Screen name="checkout" options={{ title: t('checkout.title'), presentation: 'modal' }} />
      <Stack.Screen name="payment-result" options={{ headerShown: false }} />
      <Stack.Screen name="lists/index" options={{ title: t('list.saved') }} />
      <Stack.Screen name="lists/[id]" options={{ title: t('list.title') }} />
      <Stack.Screen name="legal/[doc]" options={{ title: '' }} />
      <Stack.Screen name="login" options={{ title: t('my.login'), presentation: 'modal' }} />
      <Stack.Screen name="signup" options={{ title: t('signup.title'), presentation: 'modal' }} />
      <Stack.Screen name="reset-password" options={{ title: t('reset.title'), presentation: 'modal' }} />
      <Stack.Screen name="auth/callback" options={{ headerShown: false }} />
      <Stack.Screen
        name="terms-consent"
        options={{ title: t('consent.title'), presentation: 'modal', gestureEnabled: false, headerBackVisible: false }}
      />
      <Stack.Screen name="membership" options={{ title: t('membership.title') }} />
      <Stack.Screen name="settings" options={{ title: t('my.settings') }} />
      <Stack.Screen name="rewards" options={{ title: t('rewards.title') }} />
      <Stack.Screen name="saved" options={{ title: t('saved.title') }} />
      <Stack.Screen name="ingredients" options={{ title: t('ingredients.title') }} />
    </Stack>
  );
}
