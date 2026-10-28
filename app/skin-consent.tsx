import Ionicons from '@expo/vector-icons/Ionicons';
import { useRouter } from 'expo-router';
import { useEffect, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Button } from '@/components/ui/Button';
import { Notice } from '@/components/ui/Notice';
import { theme } from '@/constants/theme';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import { skinAnalysisEnabled, skinAnalysisServerMode, skinAnalysisSupported } from '@/lib/skinAnalysis';
import { useSkinProfileStore } from '@/store/skinProfileStore';

/** Separate consent before skin capture. Manual concern selection never needs the camera. */
export default function SkinConsentScreen() {
  const router = useRouter();
  const { t } = useI18n();
  const [agreed, setAgreed] = useState(false);
  const profile = useSkinProfileStore((s) => s.profile);
  const hydrate = useSkinProfileStore((s) => s.hydrate);
  const canCapture = skinAnalysisEnabled && skinAnalysisSupported;

  useEffect(() => {
    void hydrate().catch(() => {});
  }, [hydrate]);

  const points: TranslationKey[] = [
    'skinFlow.consent.notMedical',
    ...(canCapture
      ? [skinAnalysisServerMode ? ('skinFlow.consent.serverPhoto' as const) : ('skinFlow.consent.localPhoto' as const)]
      : []),
    'skinFlow.consent.storedOnDevice',
    'skinFlow.consent.onlyConcerns',
  ];

  return (
    <SafeAreaView style={styles.screen} edges={['bottom']}>
      <ScrollView contentContainerStyle={styles.content}>
        <View style={styles.icon}>
          <Ionicons name="water-outline" size={28} color={theme.colors.rose} />
        </View>
        <Text style={styles.title} accessibilityRole="header">
          {t('skinFlow.consent.title')}
        </Text>
        <Text style={styles.body}>{t('skinFlow.consent.intro')}</Text>
        <View style={styles.points}>
          {points.map((key) => (
            <View key={key} style={styles.point}>
              <Ionicons name="shield-checkmark-outline" size={18} color={theme.colors.success} />
              <Text style={styles.pointText}>{t(key)}</Text>
            </View>
          ))}
        </View>

        {canCapture ? (
          <Pressable
            onPress={() => setAgreed((v) => !v)}
            accessibilityRole="checkbox"
            accessibilityState={{ checked: agreed }}
            style={styles.agree}>
            <Ionicons name={agreed ? 'checkbox' : 'square-outline'} size={24} color={agreed ? theme.colors.rose : theme.colors.inkFaint} />
            <Text style={styles.agreeText}>{t('skinFlow.consent.agree')}</Text>
          </Pressable>
        ) : (
          <Notice tone="warning" body={t('skinFlow.consent.captureOff')} />
        )}
      </ScrollView>
      <View style={styles.footer}>
        {canCapture ? (
          <Button
            label={t('skinFlow.consent.start')}
            icon="camera-outline"
            disabled={!agreed}
            onPress={() => router.push('/skin-analysis')}
          />
        ) : null}
        {profile ? (
          <Button label={t('skinFlow.useSaved')} variant="secondary" onPress={() => router.push('/skin-recommendations')} />
        ) : null}
        <Button label={t('skinFlow.manual')} variant="ghost" onPress={() => router.push('/skin-recommendations')} />
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  content: { padding: theme.spacing.xl, gap: 14 },
  icon: {
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: theme.colors.roseSoft,
    alignItems: 'center',
    justifyContent: 'center',
  },
  title: { fontSize: theme.font.h2, fontWeight: '800', color: theme.colors.ink },
  body: { fontSize: theme.font.body, color: theme.colors.inkMuted, lineHeight: 22 },
  points: { gap: 12, marginTop: 4 },
  point: { flexDirection: 'row', gap: 10, alignItems: 'flex-start' },
  pointText: { flex: 1, fontSize: theme.font.small, color: theme.colors.ink, lineHeight: 20 },
  agree: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    minHeight: theme.hitTarget + 8,
    padding: 12,
    marginTop: 8,
    borderRadius: theme.radius.md,
    borderWidth: 1,
    borderColor: theme.colors.border,
    backgroundColor: theme.colors.card,
  },
  agreeText: { flex: 1, fontSize: theme.font.body, fontWeight: '700', color: theme.colors.ink },
  footer: {
    gap: 8,
    paddingHorizontal: theme.spacing.lg,
    paddingTop: 12,
    paddingBottom: 8,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: theme.colors.border,
  },
});
