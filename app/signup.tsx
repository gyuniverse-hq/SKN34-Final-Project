import { useLocalSearchParams, useRouter } from 'expo-router';
import { useState } from 'react';
import { Pressable, Text, View } from 'react-native';
import { AuthInput, AuthScreen, authStyles, FormMessage } from '@/components/auth/AuthForm';
import { Button } from '@/components/ui/Button';
import {
  authErrorMessageKey,
  isAuthConfigured,
  resendSignupCode,
  signUpWithEmail,
  verifySignupCode,
} from '@/lib/auth';
import { useI18n } from '@/lib/i18n';

const MIN_CODE_LENGTH = 6;

export default function SignupScreen() {
  const router = useRouter();
  const { t } = useI18n();
  const params = useLocalSearchParams<{ email?: string; verify?: string }>();
  const [email, setEmail] = useState(params.email ?? '');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [code, setCode] = useState('');
  const [step, setStep] = useState<'form' | 'verify'>(params.verify && params.email ? 'verify' : 'form');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const configured = isAuthConfigured();
  const address = email.trim();

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      await action();
    } catch (e) {
      setError(t(authErrorMessageKey(e)));
    } finally {
      setBusy(false);
    }
  };

  const submitForm = () => {
    if (password !== confirm) {
      setError(t('auth.error.passwordMismatch'));
      return;
    }
    return run(async () => {
      const { needsVerification } = await signUpWithEmail(address, password);
      if (needsVerification) setStep('verify');
      else router.dismissTo('/my');
    });
  };

  const submitCode = () =>
    run(async () => {
      await verifySignupCode(address, code.trim());
      router.dismissTo('/my');
    });

  const resend = () =>
    run(async () => {
      await resendSignupCode(address);
      setInfo(t('auth.codeResent'));
    });

  if (step === 'verify') {
    return (
      <AuthScreen title={t('signup.verifyTitle')} subtitle={t('signup.verifyBody', { email: address })}>
        <View style={authStyles.form}>
          <AuthInput
            value={code}
            onChangeText={(v) => setCode(v.replace(/\D/g, ''))}
            placeholder={t('auth.code')}
            keyboardType="number-pad"
            autoComplete="one-time-code"
            textContentType="oneTimeCode"
            maxLength={10}
          />
          <FormMessage tone="error" text={error} />
          <FormMessage tone="info" text={info} />
          <Button label={t('auth.verify')} onPress={submitCode} loading={busy} disabled={code.length < MIN_CODE_LENGTH} />
          <Button label={t('auth.resendCode')} variant="ghost" onPress={resend} disabled={busy} />
        </View>
      </AuthScreen>
    );
  }

  return (
    <AuthScreen title={t('signup.title')} subtitle={t('signup.subtitle')}>
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
          autoComplete="new-password"
        />
        <AuthInput
          value={confirm}
          onChangeText={setConfirm}
          placeholder={t('auth.confirmPassword')}
          secureTextEntry
          autoComplete="new-password"
        />
        <FormMessage tone="error" text={error} />
        <Button
          label={t('signup.submit')}
          onPress={submitForm}
          loading={busy}
          disabled={!configured || !address || !password || !confirm}
        />
      </View>
      <Pressable accessibilityRole="button" style={authStyles.link} onPress={() => router.replace('/login')}>
        <Text style={authStyles.linkText}>{t('signup.haveAccount')}</Text>
      </Pressable>
    </AuthScreen>
  );
}
