import { Stack, useRouter } from 'expo-router';
import { StyleSheet, Text, View } from 'react-native';
import { Button } from '@/components/ui/Button';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';

export default function SkinRecommendationsScreen() {
  const { t } = useI18n();
  const router = useRouter();
  return <View style={styles.screen}>
    <Stack.Screen options={{ title: t('skin.recommend') }} />
    <Text accessibilityRole="header" style={styles.title}>{t('skin.recommend')}</Text>
    <Text style={styles.body}>{t('skin.recommendPending')}</Text>
    <Button variant="secondary" label={t('skin.backToResult')} onPress={() => router.back()} />
  </View>;
}

const styles = StyleSheet.create({
  screen: { flex: 1, justifyContent: 'center', padding: 20, gap: 24, backgroundColor: theme.colors.surface },
  title: { fontSize: 24, fontWeight: '700', color: theme.colors.ink },
  body: { fontSize: 16, lineHeight: 25, color: theme.colors.inkMuted },
});
