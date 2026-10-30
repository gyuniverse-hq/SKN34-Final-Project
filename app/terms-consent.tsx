import { useRouter } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';
import { AuthScreen, authStyles, FormMessage } from '@/components/auth/AuthForm';
import { hasAllConsents, NO_CONSENT, TermsAgreement } from '@/components/auth/TermsAgreement';
import { Button } from '@/components/ui/Button';
import { useSaveTermsConsent } from '@/hooks/useTermsConsent';
import { ApiError } from '@/lib/api';
import { signOut, useAuth } from '@/lib/auth';
import { useI18n } from '@/lib/i18n';

/** Asked after sign-in when the server has no record of the current terms (e.g. first Google sign-in). */
export default function TermsConsentScreen() {
  const router = useRouter();
  const { t } = useI18n();
  const { user } = useAuth();
  const saveConsent = useSaveTermsConsent();
  const [consent, setConsent] = useState(NO_CONSENT);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const close = () => (router.canGoBack() ? router.back() : router.replace('/my'));

  const submit = async () => {
    if (!user) return close();
    setBusy(true);
    setError(null);
    try {
      await saveConsent(user.id);
      close();
    } catch (e) {
      setError(t(e instanceof ApiError && e.code === 'terms_outdated' ? 'consent.updateApp' : 'consent.failed'));
    } finally {
      setBusy(false);
    }
  };

  const decline = async () => {
    setBusy(true);
    await signOut().catch(() => {});
    setBusy(false);
    close();
  };

  return (
    <AuthScreen title={t('consent.title')} subtitle={t('consent.body')}>
      <View style={authStyles.form}>
        <TermsAgreement
          value={consent}
          onChange={setConsent}
          onOpenDoc={(doc) => router.push({ pathname: '/legal/[doc]', params: { doc } })}
        />
        <FormMessage tone="error" text={error} />
        <Button label={t('consent.submit')} onPress={submit} loading={busy} disabled={!hasAllConsents(consent)} />
        <Button label={t('auth.logout')} variant="ghost" onPress={decline} disabled={busy} />
      </View>
    </AuthScreen>
  );
}
