import { useLocalSearchParams, useRouter } from 'expo-router';
import { useState } from 'react';
import { Pressable, Text, View } from 'react-native';
import { AuthInput, AuthScreen, authStyles, FormMessage } from '@/components/auth/AuthForm';
import { hasAllConsents, NO_CONSENT, TermsAgreement } from '@/components/auth/TermsAgreement';
import { Button } from '@/components/ui/Button';
import { useSaveTermsConsent } from '@/hooks/useTermsConsent';
import {
  authErrorMessageKey,
  getCurrentUserId,
  isAuthConfigured,
  isValidEmail,
  MIN_PASSWORD_LENGTH,
  newPasswordError,
  resendSignupCode,
  signUpWithEmail,
  verifySignupCode,
} from '@/lib/auth';
import { useI18n } from '@/lib/i18n';
import { loginHref, parseLoginReturnTo } from '@/lib/routes';

const MIN_CODE_LENGTH = 6;

export default function SignupScreen() {
  const router = useRouter();
  const { t } = useI18n();
  const params = useLocalSearchParams<{ email?: string; verify?: string; returnTo?: string }>();
  const returnTo = parseLoginReturnTo(params.returnTo);
  const saveConsent = useSaveTermsConsent();
  const [email, setEmail] = useState(params.email ?? '');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [consent, setConsent] = useState(NO_CONSENT);
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

  /** The account exists and is signed in. Consent was given on the form; the gate asks again if saving fails. */
  const finish = async () => {
    const userId = await getCurrentUserId();
    if (userId) await saveConsent(userId).catch(() => {});
    if (returnTo) router.replace(`/${returnTo}`);
    else router.dismissTo('/my');
  };

  const submitForm = () => {
    const problem = isValidEmail(address) ? newPasswordError(password, confirm) : 'auth.error.invalidEmail';
    if (problem) {
      setError(t(problem, { min: MIN_PASSWORD_LENGTH }));
      return;
    }
    return run(async () => {
      const { needsVerification } = await signUpWithEmail(address, password);
      if (needsVerification) setStep('verify');
      else await finish();
    });
  };

  const submitCode = () =>
    run(async () => {
      await verifySignupCode(address, code.trim());
      await finish();
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
        <FormMessage tone="info" text={t('auth.passwordHint', { min: MIN_PASSWORD_LENGTH })} />
        <TermsAgreement
          value={consent}
          onChange={setConsent}
          onOpenDoc={(doc) => router.push({ pathname: '/legal/[doc]', params: { doc } })}
        />
        <FormMessage tone="error" text={error} />
        <Button
          label={t('signup.submit')}
          onPress={submitForm}
          loading={busy}
          disabled={!configured || !address || !password || !confirm || !hasAllConsents(consent)}
        />
      </View>
      <Pressable accessibilityRole="button" style={authStyles.link} onPress={() => router.replace(loginHref(returnTo))}>
        <Text style={authStyles.linkText}>{t('signup.haveAccount')}</Text>
      </Pressable>
    </AuthScreen>
  );
}
