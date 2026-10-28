import Ionicons from '@expo/vector-icons/Ionicons';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { theme } from '@/constants/theme';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import type { SkinConcern } from '@/types';

/** Editable skin concern filters; suggested ones come from the on-device result. */
export function ConcernPicker({
  concerns,
  selected,
  suggested,
  onToggle,
}: {
  concerns: readonly SkinConcern[];
  selected: readonly SkinConcern[];
  suggested: readonly SkinConcern[];
  onToggle: (concern: SkinConcern) => void;
}) {
  const { t } = useI18n();
  return (
    <View style={styles.list}>
      {concerns.map((c) => {
        const on = selected.includes(c);
        return (
          <Pressable
            key={c}
            onPress={() => onToggle(c)}
            accessibilityRole="checkbox"
            accessibilityState={{ checked: on }}
            accessibilityHint={suggested.includes(c) ? t('skinFlow.suggested') : undefined}
            style={({ pressed }) => [styles.row, on && styles.rowOn, pressed && { opacity: 0.85 }]}>
            <Ionicons
              name={on ? 'checkbox' : 'square-outline'}
              size={22}
              color={on ? theme.colors.rose : theme.colors.inkFaint}
            />
            <View style={styles.copy}>
              <Text style={styles.label}>{t(`concern.${c}` as TranslationKey)}</Text>
              <Text style={styles.body}>{t(`concern.${c}.body` as TranslationKey)}</Text>
            </View>
            {suggested.includes(c) ? <Text style={styles.suggested}>{t('skinFlow.suggested')}</Text> : null}
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  list: { gap: 8 },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    minHeight: theme.hitTarget + 12,
    padding: 12,
    borderRadius: theme.radius.md,
    borderWidth: 1,
    borderColor: theme.colors.border,
    backgroundColor: theme.colors.card,
  },
  rowOn: { borderColor: theme.colors.rose, backgroundColor: theme.colors.roseSoft },
  copy: { flex: 1, gap: 2 },
  label: { fontSize: theme.font.body, fontWeight: '700', color: theme.colors.ink },
  body: { fontSize: 12, color: theme.colors.inkMuted, lineHeight: 17 },
  suggested: { fontSize: 11, fontWeight: '800', color: theme.colors.accent },
});
