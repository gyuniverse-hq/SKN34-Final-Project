import { memo } from 'react';
import { Pressable, StyleSheet, Text } from 'react-native';
import { CelebrityAvatar } from './CelebrityAvatar';
import type { Celebrity } from '@/constants/celebrities';
import { homeType } from '@/constants/homeLayout';
import { theme } from '@/constants/theme';

export const CelebrityCard = memo(function CelebrityCard({ celebrity, name, onPress, width }: {
  celebrity: Celebrity; name: string; onPress: () => void; width?: number;
}) {
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={[name, celebrity.group].filter(Boolean).join(', ')}
      onPress={onPress} style={({ pressed }) => [width !== undefined && { width }, pressed && styles.pressed]}>
      <CelebrityAvatar id={celebrity.id} name={name} />
      <Text style={styles.name}>{name}</Text>
      {!!celebrity.group && <Text style={styles.group}>{celebrity.group}</Text>}
    </Pressable>
  );
});

const styles = StyleSheet.create({
  name: { ...homeType(15), fontWeight: '600', color: theme.colors.ink, marginTop: 6 },
  group: { ...homeType(11), color: theme.colors.inkMuted, marginTop: 1 },
  pressed: { opacity: 0.82 },
});
