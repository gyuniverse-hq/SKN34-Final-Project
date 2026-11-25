import Ionicons from '@expo/vector-icons/Ionicons';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { theme } from '@/constants/theme';
import { useI18n, type TranslationKey } from '@/lib/i18n';

export type ConsentItem = 'terms' | 'privacy' | 'age';
export type ConsentState = Record<ConsentItem, boolean> & { arActivityConsent?: boolean; cameraFeaturesConsent?: boolean };

const ITEMS: { key: ConsentItem; label: TranslationKey; doc?: 'terms' | 'privacy' }[] = [
  { key: 'terms', label: 'consent.terms', doc: 'terms' },
  { key: 'privacy', label: 'consent.privacy', doc: 'privacy' },
  { key: 'age', label: 'consent.age' },
];

export const NO_CONSENT: ConsentState = { terms: false, privacy: false, age: false };

export function hasAllConsents(state: ConsentState) {
  return ITEMS.every((item) => state[item.key]);
}

/** Each optional purpose can also be selected independently. */
export function TermsAgreement({
  value,
  onChange,
  onOpenDoc,
}: {
  value: ConsentState;
  onChange: (next: ConsentState) => void;
  onOpenDoc: (doc: 'terms' | 'privacy') => void;
}) {
  const { t } = useI18n();
  const all = hasAllConsents(value) && !!value.arActivityConsent && !!value.cameraFeaturesConsent;
  return (
    <View style={styles.box}>
      <CheckRow
        label={t('consent.all')}
        checked={all}
        strong
        onPress={() => onChange({ terms: !all, privacy: !all, age: !all, cameraFeaturesConsent: !all, arActivityConsent: !all })}
      />
      <View style={styles.divider} />
      {ITEMS.map((item) => (
        <View key={item.key} style={styles.row}>
          <CheckRow
            label={t(item.label)}
            checked={value[item.key]}
            onPress={() => onChange({ ...value, [item.key]: !value[item.key] })}
          />
          {item.doc ? (
            <Pressable accessibilityRole="link" hitSlop={8} onPress={() => onOpenDoc(item.doc!)}>
              <Text style={styles.view}>{t('consent.view')}</Text>
            </Pressable>
          ) : null}
        </View>
      ))}
      <View style={styles.divider} />
      <CheckRow label={t('consent.cameraOptional')} checked={!!value.cameraFeaturesConsent}
        onPress={() => onChange({ ...value, cameraFeaturesConsent: !value.cameraFeaturesConsent })} />
      <Text style={styles.note}>{t('consent.cameraDetails')}</Text>
      <CheckRow label={t('consent.arOptional')} checked={!!value.arActivityConsent}
        onPress={() => onChange({ ...value, arActivityConsent: !value.arActivityConsent })} />
      <Text style={styles.note}>{t('consent.arDetails')}</Text>
    </View>
  );
}

function CheckRow({
  label,
  checked,
  strong,
  onPress,
}: {
  label: string;
  checked: boolean;
  strong?: boolean;
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
      <Text style={[styles.label, strong && styles.strong]}>{label}</Text>
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
  divider: { height: StyleSheet.hairlineWidth, backgroundColor: theme.colors.border },
  row: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  check: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: 10, minHeight: theme.hitTarget },
  label: { flex: 1, fontSize: theme.font.small, color: theme.colors.ink, lineHeight: 19 },
  note: { marginLeft: 32, paddingBottom: 10, fontSize: theme.font.small, lineHeight: 19, color: theme.colors.inkMuted },
  strong: { fontSize: theme.font.body, fontWeight: '700' },
  view: { fontSize: theme.font.small, fontWeight: '700', color: theme.colors.inkMuted, textDecorationLine: 'underline' },
});
