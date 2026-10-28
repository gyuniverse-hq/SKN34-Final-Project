import { Stack, useRouter } from 'expo-router';
import { useEffect, useMemo, useRef, useState } from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ConcernPicker } from '@/components/skin/ConcernPicker';
import { Button } from '@/components/ui/Button';
import { Notice } from '@/components/ui/Notice';
import { LoadingState } from '@/components/ui/StateViews';
import { theme } from '@/constants/theme';
import { formatDate } from '@/lib/format';
import { useI18n } from '@/lib/i18n';
import { searchHref, SKIN_CONCERNS } from '@/lib/routes';
import { suggestConcerns, toggleConcern } from '@/lib/skinFilters';
import { useSkinProfileStore } from '@/store/skinProfileStore';
import type { SkinConcern } from '@/types';

/** Review / edit filters derived from the on-device skin result, then browse products. */
export default function SkinRecommendationsScreen() {
  const router = useRouter();
  const { t, language } = useI18n();
  const profile = useSkinProfileStore((s) => s.profile);
  const hydrate = useSkinProfileStore((s) => s.hydrate);
  const [hydrated, setHydrated] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const suggested = useMemo(() => suggestConcerns(profile), [profile]);
  const [selected, setSelected] = useState<SkinConcern[]>([]);
  const seeded = useRef(false);

  useEffect(() => {
    hydrate()
      .catch(() => setLoadFailed(true))
      .finally(() => setHydrated(true));
  }, [hydrate]);

  useEffect(() => {
    if (!hydrated || seeded.current) return;
    seeded.current = true;
    setSelected(suggested);
  }, [hydrated, suggested]);

  if (!hydrated) return <LoadingState />;

  return (
    <SafeAreaView style={styles.screen} edges={['bottom']}>
      <Stack.Screen options={{ title: t('skinFlow.resultTitle') }} />
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.title} accessibilityRole="header">
          {t('skinFlow.resultTitle')}
        </Text>
        <Text style={styles.body}>
          {profile
            ? t('skinFlow.resultFrom', { date: formatDate(profile.registeredAt, language) })
            : t('skinFlow.noResult')}
        </Text>
        {loadFailed ? <Notice tone="warning" body={t('skin.loadFailed')} /> : null}
        {profile && suggested.length === 0 ? <Notice body={t('skinFlow.noSuggestions')} /> : null}

        <ConcernPicker
          concerns={SKIN_CONCERNS}
          selected={selected}
          suggested={suggested}
          onToggle={(c) => setSelected((prev) => toggleConcern(prev, c))}
        />

        <Notice tone="neutral" title={t('skinFlow.notMedicalTitle')} body={t('skinFlow.notMedicalBody')} />
      </ScrollView>
      <View style={styles.footer}>
        <Button
          label={t('skinFlow.browse', { count: selected.length })}
          icon="search-outline"
          disabled={selected.length === 0}
          onPress={() => router.push(searchHref({ concerns: selected, source: 'skin' }))}
        />
        <Button
          label={t('skinFlow.skip')}
          variant="secondary"
          onPress={() => router.push(searchHref({ source: 'skin' }))}
        />
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  content: { padding: theme.spacing.lg, gap: 14, paddingBottom: 32 },
  title: { fontSize: theme.font.h2, fontWeight: '800', color: theme.colors.ink },
  body: { fontSize: theme.font.body, color: theme.colors.inkMuted, lineHeight: 22 },
  footer: {
    gap: 8,
    paddingHorizontal: theme.spacing.lg,
    paddingTop: 12,
    paddingBottom: 8,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: theme.colors.border,
  },
});
