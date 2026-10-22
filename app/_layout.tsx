import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Stack } from 'expo-router';
import Head from 'expo-router/head';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { useEffect, useState } from 'react';
import { theme } from '@/constants/theme';
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

  useEffect(() => {
    SplashScreen.hideAsync().catch(() => {});
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <Head>
        <title>VISHUE</title>
      </Head>
      <StatusBar style="dark" />
      <RootStack />
    </QueryClientProvider>
  );
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
      <Stack.Screen name="product/[id]" options={{ title: '' }} />
      <Stack.Screen name="look/[id]" options={{ title: '' }} />
      <Stack.Screen name="checkout" options={{ title: t('checkout.title'), presentation: 'modal' }} />
      <Stack.Screen name="lists/index" options={{ title: t('list.saved') }} />
      <Stack.Screen name="lists/[id]" options={{ title: t('list.title') }} />
      <Stack.Screen name="legal/[doc]" options={{ title: '' }} />
      <Stack.Screen name="login" options={{ title: t('my.login'), presentation: 'modal' }} />
      <Stack.Screen name="signup" options={{ title: t('signup.title'), presentation: 'modal' }} />
      <Stack.Screen name="reset-password" options={{ title: t('reset.title'), presentation: 'modal' }} />
      <Stack.Screen name="auth/callback" options={{ headerShown: false }} />
      <Stack.Screen name="membership" options={{ title: t('membership.title') }} />
      <Stack.Screen name="rewards" options={{ title: t('rewards.title') }} />
      <Stack.Screen name="saved" options={{ title: t('saved.title') }} />
      <Stack.Screen name="ingredients" options={{ title: t('ingredients.title') }} />
    </Stack>
  );
}
