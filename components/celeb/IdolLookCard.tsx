import Ionicons from '@expo/vector-icons/Ionicons';
import { memo } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Badge, type BadgeTone } from '@/components/ui/Badge';
import { ProductImage } from '@/components/ui/ProductImage';
import { theme } from '@/constants/theme';
import type { IdolLook } from '@/types';

interface Props {
  look: IdolLook;
  statusLabel: string;
  statusTone: BadgeTone;
  onPress: () => void;
  width?: number;
}

/** YouTube-backed look: video thumbnail, channel and product verification status. */
export const IdolLookCard = memo(function IdolLookCard({ look, statusLabel, statusTone, onPress, width }: Props) {
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={`${look.displayName}. ${statusLabel}`}
      style={({ pressed }) => [styles.card, width ? { width } : null, pressed && { opacity: 0.9 }]}>
      <View>
        <ProductImage uri={look.video.thumbnailUrl} style={styles.thumb} compact />
        <View style={styles.play} pointerEvents="none">
          <Ionicons name="play" size={18} color={theme.colors.white} />
        </View>
      </View>
      <View style={styles.body}>
        <Text style={styles.name} numberOfLines={2}>
          {look.displayName}
        </Text>
        {look.video.channelName ? (
          <Text style={styles.channel} numberOfLines={1}>
            YouTube · {look.video.channelName}
          </Text>
        ) : null}
        <Badge label={statusLabel} tone={statusTone} />
      </View>
    </Pressable>
  );
});

const styles = StyleSheet.create({
  card: {
    overflow: 'hidden',
    borderRadius: theme.radius.lg,
    borderWidth: 1,
    borderColor: theme.colors.border,
    backgroundColor: theme.colors.card,
  },
  thumb: { width: '100%', aspectRatio: 16 / 9, backgroundColor: theme.colors.surfaceAlt },
  play: {
    position: 'absolute',
    alignSelf: 'center',
    top: '50%',
    marginTop: -20,
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: 'rgba(120,44,76,0.85)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  body: { padding: 12, gap: 6 },
  name: { fontSize: theme.font.body, fontWeight: '800', color: theme.colors.ink },
  channel: { fontSize: 12, fontWeight: '600', color: theme.colors.accent },
});
