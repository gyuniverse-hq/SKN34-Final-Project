import Ionicons from '@expo/vector-icons/Ionicons';
import { useFocusEffect, useRouter } from 'expo-router';
import { useCallback, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { BottomSheet } from '@/components/ui/BottomSheet';
import { Button } from '@/components/ui/Button';
import { defaultNickname, localNicknameKey, readNickname, saveNickname, validNickname } from '@/lib/localNickname';
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import { ListRow } from '@/components/ui/ListRow';
import { MenuSection } from '@/components/ui/MenuSection';
import { homeLayout, tabTitle } from '@/constants/homeLayout';
import { theme } from '@/constants/theme';
import { authErrorMessageKey, signOut, useAuth } from '@/lib/auth';
import { confirmAction, notify } from '@/lib/confirm';
import { useI18n } from '@/lib/i18n';
import { useShoppingListStore } from '@/store/shoppingListStore';

function MemberProfile({ owner }: { owner: string }) {
  const { t } = useI18n();
  const nickname = useQuery({ queryKey: [localNicknameKey(owner)], queryFn: () => readNickname(owner) });
  const { refetch } = nickname;
  useFocusEffect(useCallback(() => { void refetch({ cancelRefetch: false }); }, [refetch]));
  const displayName = nickname.data ?? defaultNickname(owner);
  const cache = useQueryClient();
  const { bottom } = useSafeAreaInsets();
  const [draft, setDraft] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const name = draft?.trim().normalize('NFC') ?? '';
  const valid = validNickname(name);
  const save = async () => {
    if (!valid || busy) return;
    setBusy(true);
    try {
      const saved = await saveNickname(owner, name);
      await cache.cancelQueries({ queryKey: [localNicknameKey(owner)] });
      cache.setQueryData([localNicknameKey(owner)], saved);
      setDraft(null);
    } catch { setFailed(true); }
    finally { setBusy(false); }
  };
  return <>
    <ListRow prominent icon="person-circle-outline" label={displayName}
      onPress={() => { setFailed(false); setDraft(displayName); }} />
    {draft !== null && <BottomSheet title={t('my.nicknameEdit')} closeLabel={t('common.cancel')} bottomInset={bottom}
      onClose={() => { if (!busy) setDraft(null); }}>
      <View style={styles.editor}>
        <TextInput editable={!busy} value={draft} onChangeText={setDraft} autoFocus autoCapitalize="none"
          accessibilityLabel={t('my.nicknameEdit')} style={styles.input} />
        <Text style={styles.hint}>{t('my.nicknameHelp')}</Text>
        {failed && <Text accessibilityRole="alert">{t('my.nicknameError')}</Text>}
        <Button label={t('my.nicknameSave')} disabled={!valid || busy} loading={busy} onPress={save} />
      </View>
    </BottomSheet>}
  </>;
}

export default function MyScreen() {
  const router = useRouter();
  const { t } = useI18n();
  const { user } = useAuth();
  const listCount = useShoppingListStore((s) => s.lists.length);
  const logout = () =>
    confirmAction(t('auth.logoutConfirm'), t('auth.logout'), t('common.cancel'), () => {
      signOut().catch((e) => notify(t(authErrorMessageKey(e))));
    });

  return (
    <SafeAreaView style={styles.screen} edges={['top']}>
      <ScrollView contentContainerStyle={styles.content}>
        <View style={styles.header}>
          <Text accessibilityRole="header" style={tabTitle}>{t('tabs.my')}</Text>
          <Pressable accessibilityRole="button" accessibilityLabel={t('my.settings')} onPress={() => router.push('/settings')}
            style={({ pressed }) => [styles.settingsButton, pressed && styles.pressed]}>
            <Ionicons name="settings-outline" size={24} color={theme.colors.roseDark} />
          </Pressable>
        </View>
        <View style={styles.profile}>
          {user ? (
            <MemberProfile key={user.id} owner={user.id} />
          ) : (
            <ListRow prominent icon="person-circle-outline" label={t('my.login')} onPress={() => router.push('/login')} />
          )}
        </View>
        <MenuSection title={t('my.benefits')}>
          <ListRow icon="star-outline" label={t('my.membership')} onPress={() => router.push('/membership')} />
          <ListRow icon="ticket-outline" label={t('my.rewards')} onPress={() => router.push('/rewards')} />
        </MenuSection>
        <MenuSection title={t('my.library')}>
          <ListRow icon="heart-outline" label={t('my.saved')} onPress={() => router.push('/saved')} />
          <ListRow icon="list-outline" label={t('my.lists')} value={listCount ? String(listCount) : undefined} onPress={() => router.push('/lists')} />
        </MenuSection>
        <MenuSection title={t('my.tools')}>
          <ListRow icon="flask-outline" label={t('my.ingredients')} onPress={() => router.push('/ingredients')} />
        </MenuSection>
        {user && <MenuSection>
          <ListRow icon="log-out-outline" label={t('auth.logout')} onPress={logout} />
        </MenuSection>}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: homeLayout.background },
  content: { width: '100%', maxWidth: homeLayout.maxWidth, alignSelf: 'center', paddingHorizontal: homeLayout.gutter, paddingBottom: 92 },
  header: { minHeight: homeLayout.headerHeight, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  settingsButton: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center', borderRadius: 22 },
  pressed: { backgroundColor: theme.colors.surfaceAlt },
  editor: { padding: 16, gap: 12 },
  hint: { color: theme.colors.inkMuted },
  input: { borderWidth: 1, borderColor: theme.colors.border, borderRadius: theme.radius.md, padding: 12, color: theme.colors.ink },
  profile: { marginBottom: 22, borderRadius: theme.radius.md, overflow: 'hidden' },
});
