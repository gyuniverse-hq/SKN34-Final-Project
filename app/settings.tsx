import AsyncStorage from '@react-native-async-storage/async-storage';
import { useQueryClient } from '@tanstack/react-query';
import Constants from 'expo-constants';
import { useRouter } from 'expo-router';
import { useEffect, useState } from 'react';
import { ScrollView, StyleSheet, Text } from 'react-native';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import { MemorySettingsControls } from '@/components/chat/MemorySettingsControls';
import { BottomSheet } from '@/components/ui/BottomSheet';
import { MenuSection } from '@/components/ui/MenuSection';
import { ListRow } from '@/components/ui/ListRow';
import { homeLayout, homeType } from '@/constants/homeLayout';
import { theme } from '@/constants/theme';
import { useAccountDeletion } from '@/hooks/useAccountDeletion';
import { useChatMemory } from '@/hooks/useChatMemory';
import { ApiError } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { confirmAction, notify } from '@/lib/confirm';
import { LANGUAGE_LABELS, LANGUAGES, useI18n, type LanguagePreference, type TranslationKey } from '@/lib/i18n';
import { chatRequestRecoveryPrefix, chatRoomDeletionPrefix, STORAGE_KEYS } from '@/lib/storage';
import { clearSkinTimings } from '@/lib/skinProfile';
import { useSkinProfileStore } from '@/store/skinProfileStore';
import { useCartStore } from '@/store/cartStore';
import { useChatConversationStore } from '@/store/chatConversationStore';
import { useCompareStore } from '@/store/compareStore';
import { useMakeupStore } from '@/store/makeupStore';
import { useSettingsStore } from '@/store/settingsStore';
import { useShoppingListStore } from '@/store/shoppingListStore';

export default function SettingsScreen() {
  const [languageOpen, setLanguageOpen] = useState(false);
  const { bottom } = useSafeAreaInsets();
  const router = useRouter();
  const { t, language: resolvedLanguage } = useI18n();
  const queryClient = useQueryClient();
  const language = useSettingsStore((s) => s.language);
  const setLanguage = useSettingsStore((s) => s.setLanguage);
  const cameraConsent = useSettingsStore((s) => s.cameraConsent);
  const setCameraConsent = useSettingsStore((s) => s.setCameraConsent);
  const { user } = useAuth();
  const ownerId = user?.id ?? null;
  const memory = useChatMemory(ownerId, resolvedLanguage);
  const memorySettings = memory.settings;
  const refreshMemorySettings = memory.refreshSettings;
  const [memoryMessage, setMemoryMessage] = useState<{ ownerId: string; key: TranslationKey }>();
  const deletion = useAccountDeletion();
  const options: { value: LanguagePreference; label: string }[] = [
    { value: 'system', label: t('my.languageSystem') },
    ...LANGUAGES.map((l) => ({ value: l, label: LANGUAGE_LABELS[l] })),
  ];

  useEffect(() => {
    if (!ownerId) return;
    let active = true;
    void refreshMemorySettings().catch(() => {
      if (active) setMemoryMessage({ ownerId, key: 'chat.memory.error' });
    });
    return () => { active = false; };
  }, [ownerId, refreshMemorySettings]);

  const invalidateChatMemory = (id: string) => {
    const store = useChatConversationStore.getState();
    if (store.identity?.userId === id) store.invalidateMemoryContext(store.identity.key);
  };

  const showMemoryError = (id: string, error: unknown) => {
    const conflict = error instanceof ApiError && error.code === 'memory_settings_changed';
    setMemoryMessage({ ownerId: id, key: conflict ? 'chat.memory.settingsChanged' : 'chat.memory.error' });
    if (conflict) void refreshMemorySettings().catch(() => {});
  };

  const changeMemory = async (enabled: boolean | undefined, acknowledgeNotice?: true) => {
    if (!ownerId || !memorySettings || memory.busy) return;
    try {
      const updated = await memory.updateSettings(memorySettings, enabled, acknowledgeNotice);
      if (updated.enabled !== memorySettings.enabled) invalidateChatMemory(ownerId);
      setMemoryMessage(undefined);
    } catch (error) { showMemoryError(ownerId, error); }
  };

  const deleteSavedMemories = async () => {
    if (!ownerId || !memorySettings || memory.busy) return;
    try {
      await memory.deleteAll(memorySettings);
      invalidateChatMemory(ownerId);
      setMemoryMessage({ ownerId, key: 'chat.memory.deleteAllDone' });
    } catch (error) { showMemoryError(ownerId, error); }
  };

  const deleteAll = () =>
    confirmAction(t('my.deleteDataConfirm'), t('common.delete'), t('common.cancel'), async () => {
      useCartStore.getState().reset();
      useCompareStore.getState().clear();
      useShoppingListStore.getState().clear();
      useSettingsStore.getState().reset();
      useMakeupStore.getState().reset();
      queryClient.clear();
      await clearSkinTimings();
      const deletionPrefix = chatRoomDeletionPrefix();
      const recoveryPrefix = chatRequestRecoveryPrefix();
      const scopedKeys = (await AsyncStorage.getAllKeys()).filter(key =>
        key.startsWith(`${STORAGE_KEYS.skinProfile}:`) || key.startsWith(`${STORAGE_KEYS.firstArInvitation}:`) ||
        key.startsWith(deletionPrefix) || key.startsWith(recoveryPrefix));
      await AsyncStorage.multiRemove([...Object.values(STORAGE_KEYS), ...scopedKeys]);
      useChatConversationStore.getState().clearRecoveredRoomDeletions();
      useChatConversationStore.getState().clearRequestRecoveries();
      useSkinProfileStore.getState().reset();
      notify(t('my.deleteDataDone'));
    });

  const removeAccount = (owner: string) =>
    confirmAction(t('account.deleteConfirm'), t('account.delete'), t('common.cancel'), () => {
      void deletion.submit(owner);
    });

  return (
    <SafeAreaView style={styles.screen} edges={['bottom']}>
      <ScrollView contentContainerStyle={styles.content}>
        <MenuSection title={t('my.appSettings')}>
          <ListRow icon="language-outline" label={t('my.language')}
            value={language === 'system' ? t('my.languageSystem') : LANGUAGE_LABELS[language]}
            onPress={() => setLanguageOpen(true)} />
          <ListRow icon="camera-outline" label={t('my.camera')}
            value={cameraConsent ? t('my.cameraOn') : t('my.cameraOff')}
            onPress={cameraConsent ? () => setCameraConsent(false) : undefined} />
        </MenuSection>
        {ownerId && (memorySettings || memoryMessage?.ownerId === ownerId) ? <MenuSection title={t('chat.memory.settings')}>
          {memorySettings ? <>
            <MemorySettingsControls settings={memorySettings} busy={memory.busy} showManagement
              onChange={(enabled, acknowledge) => void changeMemory(enabled, acknowledge)}
              onDeleteAll={() => void deleteSavedMemories()} />
            <ListRow icon="bookmark-outline" label={t('chat.memory.manage')}
              onPress={() => router.push({ pathname: '/chat', params: { memory: 'manage' } })} />
          </> : null}
          {memoryMessage?.ownerId === ownerId ? <Text accessibilityRole="alert" style={styles.dataNote}>
            {t(memoryMessage.key)}
          </Text> : null}
        </MenuSection> : null}
        <MenuSection title={t('my.policies')}>
          <ListRow icon="document-text-outline" label={t('my.terms')} onPress={() => router.push('/legal/terms')} />
          <ListRow icon="shield-checkmark-outline" label={t('my.privacy')} onPress={() => router.push('/legal/privacy')} />
        </MenuSection>
        <MenuSection title={t('my.accountData')}>
          <ListRow icon="trash-outline" label={t('my.deleteData')} destructive onPress={deleteAll} />
          <Text style={styles.dataNote}>{t('my.dataNote')}</Text>
          {user && <>
            <ListRow icon="person-remove-outline" label={t('account.delete')} destructive
              value={deletion.busy ? t('account.deleteSubmitting') : undefined}
              onPress={deletion.busy ? undefined : () => removeAccount(user.id)} />
            {deletion.issue && (
              <Text style={styles.dataNote} accessibilityLiveRegion="polite">
                {t(deletion.issue === 'sessionEnded' ? 'account.deleteSessionEnded' : 'account.deleteUnavailable')}
              </Text>
            )}
          </>}
        </MenuSection>
        <Text style={styles.version}>{t('my.version')} {Constants.expoConfig?.version ?? '—'}</Text>
      </ScrollView>
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
