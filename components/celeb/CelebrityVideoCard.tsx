import Ionicons from '@expo/vector-icons/Ionicons';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { StyleLookArtwork } from './StyleLookCard';
import { theme } from '@/constants/theme';

export function CelebrityVideoCard({ videoId, title, channel, productCount, onPress }: {
  videoId: string; title: string; channel: string; productCount: string; onPress: () => void;
}) {
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={[title, channel, productCount].filter(Boolean).join(', ')} onPress={onPress}
      style={({ pressed }) => [styles.card, pressed && styles.pressed]}>
      <View style={styles.image}>
        <StyleLookArtwork group="콘셉트·분위기" videoId={videoId} dim={false} />
      </View>
      <View style={styles.copy}><Text style={styles.title} numberOfLines={2}>{title}</Text>{channel ? <Text style={styles.channel} numberOfLines={1}>{channel}</Text> : null}<Text style={styles.count}>{productCount}</Text></View>
      <Ionicons name="chevron-forward" size={16} color={theme.colors.inkFaint} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: { flexDirection: 'row', alignItems: 'center', gap: 12, padding: 10, backgroundColor: theme.colors.card, borderRadius: theme.radius.lg, borderWidth: 1, borderColor: theme.colors.border },
  image: { width: 108, aspectRatio: 16 / 9, borderRadius: theme.radius.md, overflow: 'hidden', backgroundColor: theme.colors.surfaceAlt },
  copy: { flex: 1 },
  title: { color: theme.colors.ink, fontWeight: '700', fontSize: 14, lineHeight: 19 },
  channel: { color: theme.colors.inkMuted, marginTop: 4, fontSize: 12 },
  count: { color: theme.colors.inkFaint, marginTop: 2, fontSize: 11 },
  pressed: { opacity: 0.8 },
});
