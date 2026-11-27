import { Stack } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { LookCommunityFeed } from '@/components/community/LookCommunityFeed';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';

export default function CommunityMine() {
  const { t } = useI18n();
  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: theme.colors.surface }} edges={['bottom']}>
      <Stack.Screen options={{ title: t('community.mine') }} />
      <LookCommunityFeed mine />
    </SafeAreaView>
  );
}
