import { useRouter } from 'expo-router';
import { ScrollView, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { CelebrityCard } from '@/components/celeb/CelebrityCard';
import { PhotoCredit } from '@/components/celeb/PhotoCredit';
import { CELEBRITIES } from '@/constants/celebrities';
import { homeLayout, homeType, tabTitle } from '@/constants/homeLayout';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';
import { celebrityHref } from '@/lib/routes';

export default function CelebritiesScreen() {
  const router = useRouter();
  const { width } = useWindowDimensions();
  const tileWidth = (Math.min(width, homeLayout.maxWidth) - homeLayout.gutter * 2 - homeLayout.productGap) / 2;
  const { t } = useI18n();
  return (
    <SafeAreaView style={styles.screen} edges={['bottom']}>
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={tabTitle} accessibilityRole="header">{t('home.collectionCelebrity')}</Text>
        <Text style={styles.subtitle}>{t('celebrity.choose')}</Text>
        <View style={styles.list}>
          {CELEBRITIES.map((celebrity) => (
            <View key={celebrity.id} style={{ width: tileWidth }}>
              <CelebrityCard celebrity={celebrity} name={t(celebrity.nameKey)}
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
  screen: { flex: 1, backgroundColor: homeLayout.background },
  content: { width: '100%', maxWidth: homeLayout.maxWidth, alignSelf: 'center', paddingHorizontal: homeLayout.gutter, paddingTop: 10, paddingBottom: 40 },
  subtitle: { ...homeType(13), color: theme.colors.inkMuted, marginTop: 5 },
  list: { flexDirection: 'row', flexWrap: 'wrap', columnGap: homeLayout.productGap, rowGap: 18, marginTop: 18 },
});
