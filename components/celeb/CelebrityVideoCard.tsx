import Ionicons from '@expo/vector-icons/Ionicons';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { StyleLookArtwork } from './StyleLookCard';
import { theme } from '@/constants/theme';

export function CelebrityVideoCard({ videoId, title, subtitle, onPress }: {
  videoId: string; title: string; subtitle: string; onPress: () => void;
}) {
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={`${title}, ${subtitle}`} onPress={onPress}
      style={({ pressed }) => [styles.card, pressed && styles.pressed]}>
      <View style={styles.image}>
        <StyleLookArtwork group="콘셉트·분위기" videoId={videoId} />
        <View style={styles.play}><Ionicons name="play" size={16} color={theme.colors.white} /></View>
      </View>
      <View style={styles.copy}><Text style={styles.title} numberOfLines={2}>{title}</Text><Text style={styles.subtitle} numberOfLines={2}>{subtitle}</Text></View>
      <Ionicons name="chevron-forward" size={18} color={theme.colors.inkMuted} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: { flexDirection: 'row', alignItems: 'center', gap: 12, padding: 10, backgroundColor: theme.colors.card, borderRadius: theme.radius.lg, borderWidth: 1, borderColor: theme.colors.border },
  image: { width: 124, height: 82, borderRadius: theme.radius.md, overflow: 'hidden', justifyContent: 'center', alignItems: 'center' },
  play: { width: 32, height: 32, borderRadius: 16, backgroundColor: 'rgba(20,10,14,0.55)', alignItems: 'center', justifyContent: 'center' },
  copy: { flex: 1 },
  title: { color: theme.colors.ink, fontWeight: '800', fontSize: 15 },
  subtitle: { color: theme.colors.inkMuted, marginTop: 6, fontSize: 12 },
  pressed: { opacity: 0.8 },
});
