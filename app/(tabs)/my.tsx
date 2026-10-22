import AsyncStorage from '@react-native-async-storage/async-storage';
import { useQueryClient } from '@tanstack/react-query';
import Constants from 'expo-constants';
import { useRouter } from 'expo-router';
import type { ReactNode } from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { ListRow } from '@/components/ui/ListRow';
import { theme } from '@/constants/theme';
import { authErrorMessageKey, signOut, useAuth } from '@/lib/auth';
import { confirmAction, notify } from '@/lib/confirm';
import { LANGUAGE_LABELS, LANGUAGES, useI18n, type LanguagePreference } from '@/lib/i18n';
import { STORAGE_KEYS } from '@/lib/storage';
import { useCartStore } from '@/store/cartStore';
import { useMakeupStore } from '@/store/makeupStore';
import { useSettingsStore } from '@/store/settingsStore';
import { useShoppingListStore } from '@/store/shoppingListStore';

export default function MyScreen() {
  const router = useRouter();
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const language = useSettingsStore((s) => s.language);
  const setLanguage = useSettingsStore((s) => s.setLanguage);
  const cameraConsent = useSettingsStore((s) => s.cameraConsent);
  const setCameraConsent = useSettingsStore((s) => s.setCameraConsent);
  const listCount = useShoppingListStore((s) => s.lists.length);
  const { user } = useAuth();

  const options: { value: LanguagePreference; label: string }[] = [
    { value: 'system', label: t('my.languageSystem') },
    ...LANGUAGES.map((l) => ({ value: l as LanguagePreference, label: LANGUAGE_LABELS[l] })),
  ];

  const deleteAll = () =>
    confirmAction(t('my.deleteDataConfirm'), t('common.delete'), t('common.cancel'), async () => {
      useCartStore.getState().clear();
      useShoppingListStore.getState().clear();
      useSettingsStore.getState().reset();
      useMakeupStore.getState().reset();
      queryClient.clear();
      await AsyncStorage.multiRemove(Object.values(STORAGE_KEYS));
      notify(t('my.deleteDataDone'));
    });

  const logout = () =>
    confirmAction(t('auth.logoutConfirm'), t('auth.logout'), t('common.cancel'), () => {
      signOut().catch((e) => notify(t(authErrorMessageKey(e))));
    });

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      <Section title={t('my.account')}>
        {user ? (
          <>
            <ListRow icon="person-circle-outline" label={t('auth.signedInAs', { email: user.email ?? '' })} />
            <ListRow icon="log-out-outline" label={t('auth.logout')} onPress={logout} />
          </>
        ) : (
          <ListRow icon="log-in-outline" label={t('my.login')} onPress={() => router.push('/login')} />
        )}
        <ListRow icon="star-outline" label={t('my.membership')} onPress={() => router.push('/membership')} />
        <ListRow icon="ticket-outline" label={t('my.rewards')} onPress={() => router.push('/rewards')} />
        <ListRow icon="heart-outline" label={t('my.saved')} onPress={() => router.push('/saved')} />
        <ListRow icon="flask-outline" label={t('my.ingredients')} onPress={() => router.push('/ingredients')} />
      </Section>

      <Section title={t('my.language')}>
        {options.map((o) => (
          <ListRow
            key={o.value}
            icon={o.value === 'system' ? 'phone-portrait-outline' : 'language-outline'}
            label={o.label}
            selected={language === o.value}
            onPress={() => setLanguage(o.value)}
          />
        ))}
      </Section>

      <Section>
        <ListRow
          icon="list-outline"
          label={t('my.lists')}
          value={listCount ? String(listCount) : undefined}
          onPress={() => router.push('/lists')}
        />
        <ListRow
          icon="camera-outline"
          label={t('my.camera')}
          value={cameraConsent ? t('my.cameraOn') : t('my.cameraOff')}
          onPress={cameraConsent ? () => setCameraConsent(false) : undefined}
        />
      </Section>

      <Section>
        <ListRow icon="shield-checkmark-outline" label={t('my.privacy')} onPress={() => router.push('/legal/privacy')} />
        <ListRow icon="document-text-outline" label={t('my.terms')} onPress={() => router.push('/legal/terms')} />
      </Section>

      <Section>
        <ListRow icon="trash-outline" label={t('my.deleteData')} destructive onPress={deleteAll} />
      </Section>

      <Text style={styles.note}>{t('my.dataNote')}</Text>
      <Text style={styles.note}>
        {t('my.version')} {Constants.expoConfig?.version ?? '—'}
      </Text>
    </ScrollView>
  );
}

function Section({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <View style={styles.section}>
      {title ? <Text style={styles.sectionTitle}>{title}</Text> : null}
      <View style={styles.card}>{children}</View>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  content: { padding: theme.spacing.lg, paddingBottom: 40 },
  section: { marginBottom: 20 },
  sectionTitle: { fontSize: 12, fontWeight: '700', color: theme.colors.inkMuted, marginBottom: 8, marginLeft: 4, textTransform: 'uppercase' },
  card: { borderRadius: theme.radius.md, overflow: 'hidden', borderWidth: 1, borderColor: theme.colors.border },
  note: { fontSize: 12, color: theme.colors.inkFaint, textAlign: 'center', marginTop: 6 },
});
