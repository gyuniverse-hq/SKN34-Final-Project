import Ionicons from '@expo/vector-icons/Ionicons';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { theme } from '@/constants/theme';
import { useI18n, type TranslationKey } from '@/lib/i18n';

type ConsentItem = 'terms' | 'privacy';
export type ConsentState = Record<ConsentItem, boolean>;
const ITEMS: { key: ConsentItem; label: TranslationKey; link: TranslationKey; doc: 'terms' | 'service-data' }[] = [
  { key: 'terms', label: 'consent.terms', link: 'consent.viewTerms', doc: 'terms' },
  { key: 'privacy', label: 'consent.privacy', link: 'consent.viewData', doc: 'service-data' },
];
export const NO_CONSENT: ConsentState = { terms: false, privacy: false };

export function hasAllConsents(state: ConsentState) {
  return ITEMS.every((item) => state[item.key]);
}

export function TermsAgreement({
  value,
  onChange,
  onOpenDoc,
}: {
  value: ConsentState;
  onChange: (next: ConsentState) => void;
  onOpenDoc: (doc: 'terms' | 'service-data') => void;
}) {
  const { t } = useI18n();
  return (
    <View style={styles.box}>
      {ITEMS.map((item) => (
        <View key={item.key} style={styles.row}>
          <CheckRow
            label={t(item.label)}
            checked={value[item.key]}
            onPress={() => onChange({ ...value, [item.key]: !value[item.key] })}
          />
          <Pressable accessibilityRole="link" accessibilityLabel={t(item.link)} hitSlop={8} onPress={() => onOpenDoc(item.doc)}>
            <Text style={styles.view}>{t(item.link)}</Text>
          </Pressable>
        </View>
      ))}
      <Text style={styles.note}>{t('consent.cameraNotice')}</Text>
    </View>
  );
}

function CheckRow({
  label,
  checked,
  onPress,
}: {
  label: string;
  checked: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityRole="checkbox"
      accessibilityLabel={label}
      accessibilityState={{ checked }}
      onPress={onPress}
      style={styles.check}>
      <Ionicons
        name={checked ? 'checkbox' : 'square-outline'}
        size={22}
        color={checked ? theme.colors.rose : theme.colors.inkFaint}
      />
      <Text style={styles.label}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  box: {
    borderRadius: theme.radius.md,
    borderWidth: 1,
    borderColor: theme.colors.border,
    backgroundColor: theme.colors.card,
    paddingHorizontal: 12,
    paddingVertical: 4,
  },
  row: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  check: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: 10, minHeight: theme.hitTarget },
  label: { flex: 1, fontSize: theme.font.small, color: theme.colors.ink, lineHeight: 19 },
  note: { marginLeft: 32, paddingBottom: 10, fontSize: theme.font.small, lineHeight: 19, color: theme.colors.inkMuted },
  view: { fontSize: theme.font.small, fontWeight: '700', color: theme.colors.inkMuted, textDecorationLine: 'underline' },
});
