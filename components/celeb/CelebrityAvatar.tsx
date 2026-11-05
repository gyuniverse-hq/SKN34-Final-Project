import { Image } from 'expo-image';
import { LinearGradient } from 'expo-linear-gradient';
import { memo, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import type { Celebrity } from '@/constants/celebrities';
import { theme } from '@/constants/theme';

const SIZE = 72;
const RING = 2.5;

/** Story-style round entry for a celebrity; Home keeps the large photo cards. */
export const CelebrityAvatar = memo(function CelebrityAvatar({ celebrity, name, onPress }: {
  celebrity: Celebrity; name: string; onPress: () => void;
}) {
  const [imageFailed, setImageFailed] = useState(false);
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={celebrity.group ? `${name}, ${celebrity.group}` : name}
      onPress={onPress} style={({ pressed }) => [styles.item, pressed && styles.pressed]}>
      <LinearGradient colors={[theme.colors.accent, theme.colors.rose]} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={styles.ring}>
        <View style={styles.inner}>
          {imageFailed ? (
            <Text style={styles.initial}>{name.slice(0, 1)}</Text>
          ) : (
            <Image source={celebrity.image} style={styles.photo} contentFit="cover" transition={150} onError={() => setImageFailed(true)} />
          )}
        </View>
      </LinearGradient>
      <Text style={styles.name} numberOfLines={1}>{name}</Text>
      {celebrity.group ? <Text style={styles.group} numberOfLines={1}>{celebrity.group}</Text> : null}
    </Pressable>
  );
});

const styles = StyleSheet.create({
  item: { width: SIZE + 8, alignItems: 'center' },
  ring: { width: SIZE, height: SIZE, borderRadius: SIZE / 2, padding: RING },
  inner: {
    flex: 1,
    borderRadius: SIZE / 2,
    borderWidth: 2,
    borderColor: theme.colors.surface,
    backgroundColor: theme.colors.surfaceAlt,
    overflow: 'hidden',
    alignItems: 'center',
    justifyContent: 'center',
  },
  photo: { width: '100%', height: '100%' },
  initial: { fontSize: 22, fontWeight: '800', color: theme.colors.rose },
  name: { marginTop: 6, fontSize: 12, fontWeight: '800', color: theme.colors.ink },
  group: { fontSize: 10, fontWeight: '600', color: theme.colors.inkFaint, marginTop: 1 },
  pressed: { opacity: 0.85 },
});
