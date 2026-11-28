import Ionicons from '@expo/vector-icons/Ionicons';
import { Image } from 'expo-image';
import { StyleSheet, Text, View } from 'react-native';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';

const RECOMMENDED = require('@/assets/images/skin-capture/recommended.webp');
const EXAMPLES = [
  { label: 'skin.captureGuide.makeup', source: require('@/assets/images/skin-capture/makeup.webp') },
  { label: 'skin.captureGuide.lighting', source: require('@/assets/images/skin-capture/low-light.webp') },
  { label: 'skin.captureGuide.covering', source: require('@/assets/images/skin-capture/covering.webp') },
  { label: 'skin.captureGuide.angle', source: require('@/assets/images/skin-capture/head-angle.webp') },
] as const;

function ExampleImage({ source, recommended = false }: { source: number; recommended?: boolean }) {
  return (
    <View
      style={recommended ? styles.recommendedImage : styles.exampleImage}
      importantForAccessibility="no-hide-descendants"
      aria-hidden>
      <Image source={source} style={StyleSheet.absoluteFill} contentFit="cover" />
      <View style={[styles.marker, recommended && styles.recommendedMarker]}>
        <Ionicons
          name={recommended ? 'checkmark' : 'close'}
          size={12}
          color={recommended ? theme.colors.white : theme.colors.rose}
        />
      </View>
    </View>
  );
}

export function SkinCaptureGuide() {
  const { t } = useI18n();

  return (
    <View style={styles.guide}>
      <Text accessibilityRole="header" style={styles.heading}>{t('skin.captureGuide.title')}</Text>
      <View style={styles.recommendedCard}>
        <ExampleImage source={RECOMMENDED} recommended />
        <View style={styles.recommendedCopy}>
          <Text style={styles.recommendedTitle}>{t('skin.captureGuide.recommendedTitle')}</Text>
          <Text style={styles.recommendedBody}>{t('skin.captureGuide.recommendedBody')}</Text>
        </View>
      </View>
      <View style={styles.grid}>
        {EXAMPLES.map(({ label, source }) => (
          <View key={label} style={styles.exampleCard}>
            <ExampleImage source={source} />
            <Text style={styles.exampleLabel}>{t(label)}</Text>
          </View>
        ))}
      </View>
    </View>
  );
}

const card = {
  backgroundColor: theme.colors.card,
  borderColor: theme.colors.border,
  borderWidth: 1,
  borderRadius: theme.radius.md,
  overflow: 'hidden',
} as const;

const styles = StyleSheet.create({
  guide: { gap: theme.spacing.md },
  heading: { fontSize: theme.font.h2, fontWeight: '700', color: theme.colors.ink },
  recommendedCard: { ...card, flexDirection: 'row', alignItems: 'center' },
  recommendedImage: { width: 84, aspectRatio: 382 / 416, backgroundColor: theme.colors.cream },
  recommendedCopy: { flex: 1, padding: theme.spacing.md, gap: theme.spacing.xs },
  recommendedTitle: { fontSize: theme.font.body, fontWeight: '700', color: theme.colors.ink },
  recommendedBody: { fontSize: theme.font.small, lineHeight: 19, color: theme.colors.inkMuted },
  grid: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'space-between', rowGap: theme.spacing.sm },
  exampleCard: { ...card, width: '48.5%' },
  exampleImage: { aspectRatio: 576 / 416, backgroundColor: theme.colors.roseSoft },
  exampleLabel: {
    paddingHorizontal: theme.spacing.sm,
    paddingVertical: theme.spacing.sm,
    fontSize: theme.font.small,
    lineHeight: 19,
    fontWeight: '600',
    color: theme.colors.ink,
  },
  marker: {
    position: 'absolute',
    left: 6,
    bottom: 6,
    width: 18,
    height: 18,
    borderRadius: theme.radius.pill,
    borderColor: theme.colors.white,
    borderWidth: 1,
    backgroundColor: theme.colors.roseSoft,
    alignItems: 'center',
    justifyContent: 'center',
  },
  recommendedMarker: { backgroundColor: theme.colors.success },
});
