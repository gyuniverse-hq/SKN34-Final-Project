import { useState } from 'react';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import LooksScreen from '@/components/celeb/LooksScreen';
import { LookCommunityFeed } from '@/components/community/LookCommunityFeed';
import { SearchBar } from '@/components/shop/SearchBar';
import { theme } from '@/constants/theme';
import { useDebouncedValue } from '@/hooks/useDebouncedValue';
import { useI18n } from '@/lib/i18n';
import { useStyleLooks, useTutorials } from '@/lib/queries';

export default function LooksTab() {
  const router = useRouter();
  const { section } = useLocalSearchParams<{ section?: string }>();
  const { t } = useI18n();
  const community = section === 'community';
  return (
    <SafeAreaView style={styles.screen} edges={['top']}>
      <View style={styles.tabs}>
        {(['videos', 'community'] as const).map(value => {
          const selected = (value === 'community') === community;
          return (
            <Pressable key={value} accessibilityRole="tab" accessibilityState={{ selected }}
              onPress={() => router.setParams({ section: value })} style={[styles.tab, selected && styles.active]}>
              <Text style={[styles.label, selected && styles.activeLabel]}>{t(value === 'community' ? 'community.heading' : 'community.videos')}</Text>
            </Pressable>
          );
        })}
      </View>
      {community ? <LookCommunityFeed /> : <VideoLooks />}
    </SafeAreaView>
  );
}

function VideoLooks() {
  const [query, setQuery] = useState('');
  const { t } = useI18n();
  const debounced = useDebouncedValue(query.trim(), 600);
  const looks = useStyleLooks();
  const tutorials = useTutorials(debounced.length >= 2 ? debounced : undefined, 8);
  return <LooksScreen inStack searchBar={<SearchBar tonal value={query} onChangeText={setQuery} placeholder={t('looks.searchPlaceholder')} />} looks={looks} tutorials={tutorials} />;
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  tabs: { flexDirection: 'row', gap: 5, backgroundColor: theme.colors.cream, borderRadius: 14, marginHorizontal: 18, marginTop: 6, padding: 4 },
  tab: { flex: 1, minHeight: 44, justifyContent: 'center', alignItems: 'center', borderRadius: 11 },
  active: { backgroundColor: theme.colors.card },
  label: { color: theme.colors.inkMuted, fontWeight: '700' },
  activeLabel: { color: theme.colors.roseDark },
});
