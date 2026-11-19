import Ionicons from '@expo/vector-icons/Ionicons';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'expo-router';
import { useState, type ComponentProps } from 'react';
import { skinAccessKey, useSkinAccess, type SkinAccess } from '@/hooks/useSkinAccess';
import { apiPost } from '@/lib/api';
import { notify, offerAction } from '@/lib/confirm';
import { loginHref } from '@/lib/routes';
import { readSkinProfile } from '@/lib/skinProfile';
import { registerSkinReport } from '@/lib/skinRegistration';
import { STORAGE_KEYS } from '@/lib/storage';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Button } from '@/components/ui/Button';
import { EmptyState } from '@/components/ui/StateViews';
import { theme } from '@/constants/theme';
import { useI18n, type TranslationKey } from '@/lib/i18n';

const BENEFITS: { icon: ComponentProps<typeof Ionicons>['name']; key: TranslationKey }[] = [
  { icon: 'water-outline', key: 'skinAccess.benefits' },
  { icon: 'gift-outline', key: 'membership.benefit1' },
  { icon: 'ticket-outline', key: 'membership.benefit2' },
  { icon: 'scan-outline', key: 'membership.benefit3' },
];

export default function MembershipScreen() {
  const { t } = useI18n();
  const access = useSkinAccess();
  const router = useRouter();
  const cache = useQueryClient();
  const [busy, setBusy] = useState(false);
  const home = () => router.dismissTo('/(tabs)');
  async function join() {
    if (!access.owner) { router.push(loginHref('membership')); return; }
    const owner = access.owner;
    setBusy(true);
    try {
      if (!access.subscribed) {
        const status = await apiPost<SkinAccess>('/api/me/skin-access/dev-subscription', {}, { expectedUserId: owner });
        cache.setQueryData(skinAccessKey(owner), status);
      }
      const guest = await readSkinProfile();
      if (guest && !await readSkinProfile(owner)) {
        offerAction(t('skinAccess.linkReport'), t('skinAccess.link'), t('skinAccess.later'), async () => {
          try {
            await registerSkinReport(guest, owner);
            await AsyncStorage.setItem(STORAGE_KEYS.guestSkinTrial, guest.analysis.timing.runId);
            await AsyncStorage.removeItem(STORAGE_KEYS.skinProfile);
            await cache.invalidateQueries({ queryKey: skinAccessKey(owner) });
            home();
          } catch { notify(t('skin.storageFailed')); }
        }, home);
      } else home();
    } catch { notify(t('skinAccess.joinFailed')); }
    finally { setBusy(false); }
  }

  return (
    <SafeAreaView style={styles.screen} edges={['bottom']}>
      <ScrollView contentContainerStyle={styles.content}>
        <View style={styles.hero}>
          <Text style={styles.headline}>{t('membership.headline')}</Text>
          <Text style={styles.price}>{t('membership.price')}</Text>
        </View>

        <View style={styles.card}>
          {BENEFITS.map((b) => (
            <View key={b.key} style={styles.benefit}>
              <View style={styles.benefitIcon}>
                <Ionicons name={b.icon} size={20} color={theme.colors.rose} />
              </View>
              <Text style={styles.benefitText}>{t(b.key)}</Text>
            </View>
          ))}
        </View>

        <Text style={styles.sectionTitle}>{t('membership.samples')}</Text>
        <View style={styles.samples}>
          <EmptyState icon="cube-outline" title={t('membership.samplesEmpty')} />
        </View>
      </ScrollView>
      <View style={styles.footer}>
        {access.error ? <Button label={t('skin.retry')} onPress={() => { void access.retry(); }} />
          : access.subscribed ? <Button label={t('skinAccess.active')} icon="checkmark-circle-outline" loading={busy} disabled={busy} onPress={() => { void join(); }} />
          : <Button label={t(__DEV__ ? 'skinAccess.devJoin' : 'skinAccess.unavailable')} loading={busy}
              disabled={!__DEV__ || !access.ready || busy} onPress={() => { void join(); }} />}
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  content: { padding: theme.spacing.lg, paddingBottom: 32 },
  hero: { backgroundColor: theme.colors.ink, borderRadius: theme.radius.lg, padding: 22, gap: 6 },
  headline: { fontSize: theme.font.h2, fontWeight: '800', color: theme.colors.white },
  price: { fontSize: theme.font.small, color: 'rgba(255,255,255,0.75)' },
  card: { marginTop: 16, backgroundColor: theme.colors.card, borderRadius: theme.radius.md, padding: 16, gap: 14, ...theme.shadow },
  benefit: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  benefitIcon: { width: 38, height: 38, borderRadius: 19, backgroundColor: theme.colors.roseSoft, alignItems: 'center', justifyContent: 'center' },
  benefitText: { flex: 1, fontSize: theme.font.body, color: theme.colors.ink, lineHeight: 21 },
  sectionTitle: { fontSize: theme.font.title, fontWeight: '800', color: theme.colors.ink, marginTop: 26, marginBottom: 8 },
  samples: { borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.colors.border, borderStyle: 'dashed' },
  footer: {
    paddingHorizontal: theme.spacing.lg,
    paddingTop: 12,
    paddingBottom: 8,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: theme.colors.border,
  },
});
