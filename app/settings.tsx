import AsyncStorage from '@react-native-async-storage/async-storage';
import { useQueryClient } from '@tanstack/react-query';
import Constants from 'expo-constants';
import { useRouter } from 'expo-router';
import { useState } from 'react';
import { ScrollView, StyleSheet, Text } from 'react-native';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import { BottomSheet } from '@/components/ui/BottomSheet';
import { MenuSection } from '@/components/ui/MenuSection';
import { ListRow } from '@/components/ui/ListRow';
import { homeLayout, homeType } from '@/constants/homeLayout';
import { theme } from '@/constants/theme';
import { meQueryKey, useMe } from '@/lib/queries';
import type { MeResponse } from '@/types';
import { deleteAccount, setServiceConsent, type ServiceConsentKind } from '@/lib/account';
import { ApiError } from '@/lib/api';
import { signOut, useAuth } from '@/lib/auth';
import { confirmAction, notify } from '@/lib/confirm';
import { LANGUAGE_LABELS, LANGUAGES, useI18n, type LanguagePreference } from '@/lib/i18n';
import { STORAGE_KEYS } from '@/lib/storage';
import { pendingProfileKey } from '@/lib/skinRegistration';
import { clearSkinTimings, skinProfileKey } from '@/lib/skinProfile';
import { useSkinProfileStore } from '@/store/skinProfileStore';
import { useCartStore } from '@/store/cartStore';
import { useCompareStore } from '@/store/compareStore';
import { useMakeupStore } from '@/store/makeupStore';
import { useSettingsStore } from '@/store/settingsStore';
import { useShoppingListStore } from '@/store/shoppingListStore';

export default function SettingsScreen() {
  const [languageOpen, setLanguageOpen] = useState(false);
  const { bottom } = useSafeAreaInsets();
  const router = useRouter();
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const language = useSettingsStore((s) => s.language);
  const setLanguage = useSettingsStore((s) => s.setLanguage);
  const cameraConsent = useSettingsStore((s) => s.cameraConsent);
  const setCameraConsent = useSettingsStore((s) => s.setCameraConsent);
  const { user } = useAuth();
  const me = useMe(user?.id);
  const [consentKind, setConsentKind] = useState<ServiceConsentKind | null>(null);
  const [savingConsent, setSavingConsent] = useState(false);
  const terms = me.data?.user.id === user?.id ? me.data?.terms : undefined;
  const consent = consentKind === 'cameraFeatures' ? terms?.cameraFeaturesConsent : terms?.arActivityConsent;
  const consentValue = (value?: boolean | null) => value == null ? '—' : t(value ? 'my.cameraOn' : 'my.cameraOff');
  const changeConsent = async (enabled: boolean) => {
    if (!user || !consentKind || savingConsent) return;
    if (consent === enabled) return setConsentKind(null);
    setSavingConsent(true);
    try {
      const terms = await setServiceConsent(user.id, consentKind, enabled);
      const key = meQueryKey(user.id);
      await queryClient.cancelQueries({ queryKey: key });
      queryClient.setQueryData<MeResponse>(key, old => old && { ...old, terms });
      setConsentKind(null);
    } catch {
      notify(t('consent.failed'));
    } finally {
      setSavingConsent(false);
    }
  };
  const options: { value: LanguagePreference; label: string }[] = [
    { value: 'system', label: t('my.languageSystem') },
    ...LANGUAGES.map((l) => ({ value: l, label: LANGUAGE_LABELS[l] })),
  ];

  const deleteAll = () =>
    confirmAction(t('my.deleteDataConfirm'), t('common.delete'), t('common.cancel'), async () => {
      useCartStore.getState().reset();
      useCompareStore.getState().clear();
      useShoppingListStore.getState().clear();
      useSettingsStore.getState().reset();
      useMakeupStore.getState().reset();
      queryClient.clear();
      await clearSkinTimings();
      const profileKeys = (await AsyncStorage.getAllKeys()).filter(key =>
        key.startsWith(`${STORAGE_KEYS.skinProfile}:`) || key.startsWith(`${STORAGE_KEYS.firstArInvitation}:`));
      await AsyncStorage.multiRemove([...Object.values(STORAGE_KEYS), ...profileKeys]);
      useSkinProfileStore.getState().reset();
      notify(t('my.deleteDataDone'));
    });

  const removeAccount = () =>
    confirmAction(t('account.deleteConfirm'), t('account.delete'), t('common.cancel'), async () => {
      try {
        await deleteAccount();
      } catch (e) {
        const unavailable = e instanceof ApiError && e.code === 'account_deletion_unavailable';
        notify(t(unavailable ? 'account.deleteUnavailable' : 'auth.error.generic'));
        return;
      }
      if (user) await AsyncStorage.multiRemove([skinProfileKey(user.id), pendingProfileKey(user.id), `${STORAGE_KEYS.firstArInvitation}:${user.id}`]);
      useSkinProfileStore.getState().reset();
      await signOut().catch(() => {});
      queryClient.removeQueries({ queryKey: ['me'] });
      notify(t('account.deleteDone'));
    });

  return (
    <SafeAreaView style={styles.screen} edges={['bottom']}>
      <ScrollView contentContainerStyle={styles.content}>
        <MenuSection title={t('my.appSettings')}>
          <ListRow icon="language-outline" label={t('my.language')}
            value={language === 'system' ? t('my.languageSystem') : LANGUAGE_LABELS[language]}
            onPress={() => setLanguageOpen(true)} />
          {user ? <ListRow icon="camera-outline" label={t('consent.cameraTitle')}
            value={consentValue(terms?.cameraFeaturesConsent)} onPress={() => setConsentKind('cameraFeatures')} />
            : <ListRow icon="camera-outline" label={t('my.camera')} value={consentValue(cameraConsent)}
              onPress={cameraConsent ? () => setCameraConsent(false) : undefined} />}
        </MenuSection>
        <MenuSection title={t('my.policies')}>
          {user && <ListRow icon="color-palette-outline" label={t('consent.arTitle')}
            value={consentValue(terms?.arActivityConsent)}
            onPress={() => setConsentKind('arActivity')} />}
          <ListRow icon="document-text-outline" label={t('my.terms')} onPress={() => router.push('/legal/terms')} />
          <ListRow icon="shield-checkmark-outline" label={t('my.privacy')} onPress={() => router.push('/legal/privacy')} />
        </MenuSection>
        <MenuSection title={t('my.accountData')}>
          <ListRow icon="trash-outline" label={t('my.deleteData')} destructive onPress={deleteAll} />
          <Text style={styles.dataNote}>{t('my.dataNote')}</Text>
          {user && <ListRow icon="person-remove-outline" label={t('account.delete')} destructive onPress={removeAccount} />}
        </MenuSection>
        <Text style={styles.version}>{t('my.version')} {Constants.expoConfig?.version ?? '—'}</Text>
      </ScrollView>
      {user && consentKind && <BottomSheet title={t(consentKind === 'arActivity' ? 'consent.arTitle' : 'consent.cameraTitle')} closeLabel={t('common.cancel')}
        bottomInset={bottom} onClose={() => setConsentKind(null)}>
        <Text style={styles.dataNote}>{t(consentKind === 'arActivity' ? 'consent.arDetails' : 'consent.cameraDetails')}</Text>
        {[true, false].map(enabled => <ListRow key={String(enabled)} icon={enabled ? 'checkmark-outline' : 'close-outline'}
          label={t(enabled ? 'consent.arAllow' : 'consent.arDecline')} selected={enabled === consent}
          onPress={savingConsent ? undefined : () => void changeConsent(enabled)} />)}
      </BottomSheet>}
      {languageOpen && <BottomSheet title={t('my.language')} closeLabel={t('common.cancel')}
        bottomInset={bottom} onClose={() => setLanguageOpen(false)}>
        <ScrollView>
          {options.map(option => <ListRow key={option.value}
            icon={option.value === 'system' ? 'phone-portrait-outline' : 'language-outline'}
            label={option.label} selected={language === option.value}
            onPress={() => { setLanguage(option.value); setLanguageOpen(false); }} />)}
        </ScrollView>
      </BottomSheet>}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: homeLayout.background },
  content: { width: '100%', maxWidth: homeLayout.maxWidth, alignSelf: 'center', padding: homeLayout.gutter, paddingBottom: 32 },
  dataNote: { ...homeType(12), lineHeight: 18, color: theme.colors.inkMuted, backgroundColor: theme.colors.card, padding: 12 },
  version: { ...homeType(12), color: theme.colors.inkMuted, textAlign: 'center' },
});
