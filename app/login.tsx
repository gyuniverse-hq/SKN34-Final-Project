import { useLocalSearchParams, useRouter } from 'expo-router';
import { useState } from 'react';
import { Pressable, Text, View } from 'react-native';
import { AuthInput, AuthScreen, authStyles, FormMessage } from '@/components/auth/AuthForm';
import { Button } from '@/components/ui/Button';
import {
  authErrorCode,
  authErrorMessageKey,
  isAuthConfigured,
  resendSignupCode,
  signInWithEmail,
  signInWithGoogle,
} from '@/lib/auth';
import { notify } from '@/lib/confirm';
import { useI18n } from '@/lib/i18n';
import { parseLoginReturnTo, signupHref } from '@/lib/routes';

export default function LoginScreen() {
  const router = useRouter();
  const { returnTo } = useLocalSearchParams<{ returnTo?: string }>();
  const { t } = useI18n();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [googleBusy, setGoogleBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const configured = isAuthConfigured();
  const destination = parseLoginReturnTo(returnTo);
  const finishLogin = () => {
    if (destination) router.replace(`/${destination}`);
    else router.dismissTo('/my');
  };

  const submit = async () => {
    const address = email.trim();
    setBusy(true);
    setError(null);
    try {
      await signInWithEmail(address, password);
      finishLogin();
    } catch (e) {
      if (authErrorCode(e) === 'email_not_confirmed') {
        await resendSignupCode(address).catch(() => {});
        router.replace(signupHref({ returnTo: destination, verifyEmail: address }));
        return;
      }
      setError(t(authErrorMessageKey(e)));
    } finally {
      setBusy(false);
    }
  };

  const google = async () => {
    setGoogleBusy(true);
    setError(null);
    try {
      if (await signInWithGoogle()) finishLogin();
    } catch (e) {
      setError(t(authErrorMessageKey(e)));
    } finally {
      setGoogleBusy(false);
    }
  };

  return (
    <AuthScreen title={t('login.title')} subtitle={t('login.subtitle')}>
      <View style={authStyles.form}>
        <FormMessage tone="info" text={configured ? null : t('auth.notConfigured')} />
        <AuthInput
          value={email}
          onChangeText={setEmail}
          placeholder={t('login.email')}
          keyboardType="email-address"
          autoCapitalize="none"
          autoComplete="email"
        />
        <AuthInput
          value={password}
          onChangeText={setPassword}
          placeholder={t('login.password')}
          secureTextEntry
          autoComplete="password"
        />
        <FormMessage tone="error" text={error} />
        <Button
          label={t('login.submit')}
          onPress={submit}
          loading={busy}
          disabled={!configured || !email.trim() || !password}
        />
      </View>
      <Pressable accessibilityRole="button" style={authStyles.link} onPress={() => router.replace('/reset-password')}>
        <Text style={authStyles.linkText}>{t('auth.forgotPassword')}</Text>
      </Pressable>

      <View style={authStyles.divider} />

      <Button
        label={t('login.apple')}
        icon="logo-apple"
        variant="secondary"
        onPress={() => notify(t('common.comingSoon'))}
        accessibilityHint={t('common.comingSoon')}
      />
      <Button
        label={t('login.google')}
        icon="logo-google"
        variant="secondary"
        onPress={google}
        loading={googleBusy}
        disabled={!configured || busy}
        style={authStyles.gap}
      />

      <Pressable accessibilityRole="button" style={authStyles.link} onPress={() => router.replace(signupHref({ returnTo: destination }))}>
        <Text style={authStyles.linkText}>{t('login.signup')}</Text>
      </Pressable>
    </AuthScreen>
  );
}
