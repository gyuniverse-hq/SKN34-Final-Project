import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { theme } from '@/constants/theme';
import type { Shade } from '@/types';

interface Props {
  shades: Shade[];
  selectedId?: string;
  onSelect: (shade: Shade) => void;
}

export function ShadePicker({ shades, selectedId, onSelect }: Props) {
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.row}>
      {shades.map((shade) => {
        const selected = shade.id === selectedId;
        return (
          <Pressable
            key={shade.id}
            onPress={() => onSelect(shade)}
            accessibilityRole="button"
            accessibilityLabel={shade.name}
            accessibilityState={{ selected }}
            style={styles.item}>
            <View style={[styles.ring, selected && styles.ringSelected]}>
              <View style={[styles.swatch, { backgroundColor: shade.hex }]} />
            </View>
            <Text style={[styles.label, selected && styles.labelSelected]} numberOfLines={2}>
              {shade.name}
            </Text>
          </Pressable>
        );
      })}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  row: { gap: 12, paddingVertical: 4 },
  item: { width: 68, alignItems: 'center', gap: 6 },
  ring: {
    width: 48,
    height: 48,
    borderRadius: 24,
    borderWidth: 2,
    borderColor: 'transparent',
    alignItems: 'center',
    justifyContent: 'center',
  },
  ringSelected: { borderColor: theme.colors.ink },
  swatch: {
    width: 38,
    height: 38,
    borderRadius: 19,
    borderWidth: 1,
    borderColor: 'rgba(0,0,0,0.08)',
  },
  label: { fontSize: 11, color: theme.colors.inkMuted, textAlign: 'center' },
  labelSelected: { color: theme.colors.ink, fontWeight: '700' },
});
