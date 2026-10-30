import { Image } from 'expo-image';
import { LinearGradient } from 'expo-linear-gradient';
import { memo } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { theme } from '@/constants/theme';
import type { CelebLook } from '@/types';

interface Props {
  look: CelebLook;
  subtitle: string;
  onPress: () => void;
  width?: number;
}

export const LookCard = memo(function LookCard({ look, subtitle, onPress, width }: Props) {
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={`${look.title}. ${look.inspiration}`}
      style={({ pressed }) => [styles.card, width ? { width } : null, pressed && { opacity: 0.92 }]}>
      <Image source={{ uri: look.thumbnailUrl }} style={StyleSheet.absoluteFill} contentFit="cover" transition={150} />
      <LinearGradient colors={['transparent', 'rgba(20,10,14,0.85)']} style={styles.gradient} />
      <View style={styles.swatches}>
        {[look.makeup.lip, look.makeup.blush, look.makeup.eyeshadow]
          .filter((z): z is NonNullable<typeof z> => !!z)
          .map((z, i) => (
            <View key={i} style={[styles.swatch, i > 0 && styles.swatchOverlap, { backgroundColor: z.hex }]} />
          ))}
      </View>
      <View style={styles.body}>
        <Text style={styles.inspiration} numberOfLines={1}>
          {look.inspiration}
        </Text>
        <Text style={styles.title} numberOfLines={2}>
          {look.title}
        </Text>
        <Text style={styles.meta}>{subtitle}</Text>
      </View>
    </Pressable>
  );
});

const styles = StyleSheet.create({
  card: {
    aspectRatio: 3 / 4,
    borderRadius: theme.radius.lg,
    overflow: 'hidden',
    backgroundColor: theme.colors.surfaceAlt,
    justifyContent: 'flex-end',
  },
  gradient: { position: 'absolute', left: 0, right: 0, bottom: 0, top: '35%' },
  swatches: { position: 'absolute', top: 10, left: 10, flexDirection: 'row' },
  swatch: { width: 24, height: 24, borderRadius: 12, borderWidth: 2, borderColor: theme.colors.white },
  swatchOverlap: { marginLeft: -7 },
  body: { padding: 12, gap: 2 },
  inspiration: { fontSize: 11, color: 'rgba(255,255,255,0.85)', fontWeight: '600' },
  title: { fontSize: 16, color: theme.colors.white, fontWeight: '800' },
  meta: { fontSize: 12, color: 'rgba(255,255,255,0.8)' },
});
