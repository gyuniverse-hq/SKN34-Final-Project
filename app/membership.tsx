import Ionicons from '@expo/vector-icons/Ionicons';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useQueryClient } from '@tanstack/react-query';
import { Image } from 'expo-image';
import { LinearGradient } from 'expo-linear-gradient';
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
import { homeHeading, homeLayout, homeType } from '@/constants/homeLayout';
import { theme } from '@/constants/theme';
import { useI18n, type TranslationKey } from '@/lib/i18n';

const BENEFITS: { icon: ComponentProps<typeof Ionicons>['name']; title: TranslationKey; detail: TranslationKey }[] = [
  { icon: 'water-outline', title: 'skinAccess.benefits', detail: 'membership.skinDetail' },
  { icon: 'ticket-outline', title: 'membership.coupons', detail: 'rewards.memberRule' },
  { icon: 'chatbubbles-outline', title: 'membership.conversation', detail: 'membership.conversationDetail' },
  { icon: 'mic-outline', title: 'membership.voice', detail: 'membership.voiceDetail' },
  { icon: 'sparkles-outline', title: 'membership.styles', detail: 'membership.stylesDetail' },
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
          <View pointerEvents="none" aria-hidden style={styles.heroArt}>
            <Image source={require('@/assets/images/home/editorial/tint.webp')} contentFit="cover" style={StyleSheet.absoluteFill} />
            <LinearGradient colors={[homeLayout.blush, homeLayout.blush + '00']}
              start={{ x: 0, y: 0 }} end={{ x: 1, y: 0 }} style={styles.photoFade} />
          </View>
          <View style={styles.heroCopy}>
            <Text style={styles.headline}>{t('membership.headline')}</Text>
            <Text style={styles.price}>{t('membership.price')}</Text>
          </View>
        </View>

        <Text accessibilityRole="header" style={styles.sectionTitle}>{t('membership.benefitsTitle')}</Text>
        <View style={styles.card}>
          {BENEFITS.map(({ icon, title, detail }, index) => (
            <View key={title} style={[styles.benefit, index > 0 && styles.divider]}>
              <View style={styles.benefitIcon}>
                <Ionicons name={icon} size={20} color={theme.colors.rose} />
              </View>
              <View style={styles.benefitCopy}>
                <Text style={styles.benefitText}>{t(title)}</Text>
                <Text style={styles.detail}>{t(detail)}</Text>
              </View>
            </View>
          ))}
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
  screen: { flex: 1, backgroundColor: homeLayout.background },
  content: { width: '100%', maxWidth: homeLayout.maxWidth, alignSelf: 'center', padding: homeLayout.gutter, paddingBottom: 24 },
  hero: { minHeight: 164, backgroundColor: homeLayout.blush, borderRadius: theme.radius.lg, overflow: 'hidden', justifyContent: 'center' },
  heroArt: { position: 'absolute', right: 0, top: 0, bottom: 0, width: '49%', maxWidth: 220 },
  photoFade: { width: '48%', height: '100%' },
  heroCopy: { width: '68%', paddingLeft: 16, paddingVertical: 18, gap: 14 },
  headline: { ...homeType(22), fontFamily: homeLayout.displayFont, lineHeight: 30, color: theme.colors.roseDark },
  price: { ...homeType(16), fontWeight: '600', color: theme.colors.roseDark },
  sectionTitle: { ...homeHeading, marginTop: 23, marginBottom: 10 },
  card: { backgroundColor: theme.colors.card, borderRadius: theme.radius.lg, borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.colors.border, paddingHorizontal: 14 },
  benefit: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 14 },
  divider: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: theme.colors.border },
  benefitIcon: { width: 38, height: 38, borderRadius: 19, backgroundColor: theme.colors.roseSoft, alignItems: 'center', justifyContent: 'center' },
  benefitCopy: { flex: 1, gap: 4 },
  benefitText: { ...homeType(15), fontWeight: '600', color: theme.colors.ink, lineHeight: 22 },
  detail: { ...homeType(13), color: theme.colors.inkMuted, lineHeight: 19 },
  footer: {
    alignSelf: 'center', width: '100%', maxWidth: homeLayout.maxWidth,
    paddingHorizontal: theme.spacing.lg,
    paddingTop: 12,
    paddingBottom: 8,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: theme.colors.border,
  },
});
