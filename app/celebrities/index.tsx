import { useRouter } from 'expo-router';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { CelebrityCard } from '@/components/celeb/CelebrityCard';
import { PhotoCredit } from '@/components/celeb/PhotoCredit';
import { CELEBRITIES } from '@/constants/celebrities';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';
import { celebrityHref } from '@/lib/routes';

export default function CelebritiesScreen() {
  const router = useRouter();
  const { t } = useI18n();
  return (
    <SafeAreaView style={styles.screen} edges={['bottom']}>
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.title} accessibilityRole="header">{t('home.collectionCelebrity')}</Text>
        <Text style={styles.subtitle}>{t('celebrity.choose')}</Text>
        <View style={styles.list}>
          {CELEBRITIES.map((celebrity) => (
            <View key={celebrity.id} style={styles.item}>
              <CelebrityCard celebrity={celebrity} name={t(celebrity.nameKey)} label={t('home.collectionCelebrity')} wide
                onPress={() => router.push(celebrityHref(celebrity.id))} />
              <PhotoCredit celebrity={celebrity} label={t('celebrity.photoCredit')} />
            </View>
          ))}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  content: { padding: theme.spacing.lg, paddingBottom: 32 },
  title: { fontSize: theme.font.h1, fontWeight: '800', color: theme.colors.ink },
  subtitle: { fontSize: theme.font.small, color: theme.colors.inkMuted, marginTop: 6 },
  list: { gap: 18, marginTop: 22 },
  item: { gap: 5 },
});
