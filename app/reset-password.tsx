import { useRouter } from 'expo-router';
import { useState } from 'react';
import { Pressable, Text, View } from 'react-native';
import { AuthInput, AuthScreen, authStyles, FormMessage } from '@/components/auth/AuthForm';
import { Button } from '@/components/ui/Button';
import {
  authErrorMessageKey,
  isAuthConfigured,
  isValidEmail,
  MIN_PASSWORD_LENGTH,
  newPasswordError,
  sendPasswordResetCode,
  updatePassword,
  verifyRecoveryCode,
} from '@/lib/auth';
import { notify } from '@/lib/confirm';
import { useI18n } from '@/lib/i18n';

const MIN_CODE_LENGTH = 6;

export default function ResetPasswordScreen() {
  const router = useRouter();
  const { t } = useI18n();
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [step, setStep] = useState<'email' | 'reset'>('email');
  // A recovery code works once, so a failed password update must not verify it again.
  const [codeVerified, setCodeVerified] = useState(false);
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

  const sendCode = () => {
    if (!isValidEmail(address)) {
      setError(t('auth.error.invalidEmail'));
      return;
    }
    return run(async () => {
      await sendPasswordResetCode(address);
      if (step === 'reset') setInfo(t('auth.codeResent'));
      setStep('reset');
    });
  };

  const submit = () => {
    const problem = newPasswordError(password, confirm);
    if (problem) {
      setError(t(problem, { min: MIN_PASSWORD_LENGTH }));
      return;
    }
    return run(async () => {
      if (!codeVerified) {
        await verifyRecoveryCode(address, code.trim());
        setCodeVerified(true);
      }
      await updatePassword(password);
      notify(t('reset.done'));
      router.dismissTo('/my');
    });
  };

  if (step === 'reset') {
    return (
      <AuthScreen title={t('reset.title')} subtitle={t('reset.codeBody', { email: address })}>
        <View style={authStyles.form}>
          {codeVerified ? null : (
            <AuthInput
              value={code}
              onChangeText={(v) => setCode(v.replace(/\D/g, ''))}
              placeholder={t('auth.code')}
              keyboardType="number-pad"
              autoComplete="one-time-code"
              textContentType="oneTimeCode"
              maxLength={10}
            />
          )}
          <AuthInput
            value={password}
            onChangeText={setPassword}
            placeholder={t('auth.newPassword')}
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
          <FormMessage tone="info" text={t('auth.passwordHint', { min: MIN_PASSWORD_LENGTH })} />
          <FormMessage tone="error" text={error} />
          <FormMessage tone="info" text={info} />
          <Button
            label={t('reset.submit')}
            onPress={submit}
            loading={busy}
            disabled={(!codeVerified && code.length < MIN_CODE_LENGTH) || !password || !confirm}
          />
          {codeVerified ? null : (
            <Button label={t('auth.resendCode')} variant="ghost" onPress={sendCode} disabled={busy} />
          )}
        </View>
      </AuthScreen>
    );
  }

  return (
    <AuthScreen title={t('reset.title')} subtitle={t('reset.body')}>
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
        <FormMessage tone="error" text={error} />
        <Button label={t('reset.sendCode')} onPress={sendCode} loading={busy} disabled={!configured || !address} />
      </View>
      <Pressable accessibilityRole="button" style={authStyles.link} onPress={() => router.replace('/login')}>
        <Text style={authStyles.linkText}>{t('login.submit')}</Text>
      </Pressable>
    </AuthScreen>
  );
}
