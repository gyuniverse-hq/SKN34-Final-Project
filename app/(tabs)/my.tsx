import Ionicons from '@expo/vector-icons/Ionicons';
import { useRouter } from 'expo-router';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ListRow } from '@/components/ui/ListRow';
import { MenuSection } from '@/components/ui/MenuSection';
import { homeLayout, tabTitle } from '@/constants/homeLayout';
import { theme } from '@/constants/theme';
import { authErrorMessageKey, signOut, useAuth } from '@/lib/auth';
import { confirmAction, notify } from '@/lib/confirm';
import { useI18n } from '@/lib/i18n';
import { useShoppingListStore } from '@/store/shoppingListStore';

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
            <ListRow prominent icon="person-circle-outline" label={t('auth.signedInAs', { email: user.email ?? '' })} />
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
  profile: { marginBottom: 22, borderRadius: theme.radius.md, overflow: 'hidden' },
});
