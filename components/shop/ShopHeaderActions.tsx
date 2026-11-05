import Ionicons from '@expo/vector-icons/Ionicons';
import type { ComponentProps, ReactNode } from 'react';
import { useState } from 'react';
import { Modal, Pressable, StyleSheet, Text, View } from 'react-native';
import { ListRow } from '@/components/ui/ListRow';
import { theme } from '@/constants/theme';
import { LANGUAGE_LABELS, LANGUAGES, useI18n, type LanguagePreference } from '@/lib/i18n';
import { selectCartCount, useCartStore } from '@/store/cartStore';
import { useSettingsStore } from '@/store/settingsStore';

function IconButton({
  icon,
  label,
  value,
  onPress,
  children,
}: {
  icon: ComponentProps<typeof Ionicons>['name'];
  label: string;
  value?: string;
  onPress: () => void;
  children?: ReactNode;
}) {
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityValue={value ? { text: value } : undefined}
      hitSlop={6}
      style={({ pressed }) => [styles.button, pressed && styles.pressed]}>
      <Ionicons name={icon} size={22} color={theme.colors.ink} />
      {children}
    </Pressable>
  );
}

export function ShopHeaderActions({ onOpenCart }: { onOpenCart: () => void }) {
  const { t } = useI18n();
  const cartCount = useCartStore(selectCartCount);
  const language = useSettingsStore((s) => s.language);
  const setLanguage = useSettingsStore((s) => s.setLanguage);
  const [pickerOpen, setPickerOpen] = useState(false);

  const options: { value: LanguagePreference; label: string }[] = [
    { value: 'system', label: t('my.languageSystem') },
    ...LANGUAGES.map((l) => ({ value: l as LanguagePreference, label: LANGUAGE_LABELS[l] })),
  ];
  const currentLabel = options.find((o) => o.value === language)?.label;
  const badge = cartCount > 99 ? '99+' : String(cartCount);

  const choose = (value: LanguagePreference) => {
    setLanguage(value);
    setPickerOpen(false);
  };

  return (
    <View style={styles.row}>
      <IconButton
        icon="language-outline"
        label={t('shop.changeLanguage')}
        value={currentLabel}
        onPress={() => setPickerOpen(true)}
      />
      <IconButton icon="cart-outline" label={t('cart.title')} value={cartCount ? badge : undefined} onPress={onOpenCart}>
        {cartCount > 0 ? (
          <View style={styles.badge} importantForAccessibility="no-hide-descendants">
            <Text style={styles.badgeText}>{badge}</Text>
          </View>
        ) : null}
      </IconButton>

      <Modal visible={pickerOpen} transparent animationType="fade" onRequestClose={() => setPickerOpen(false)}>
        <View style={styles.overlay}>
          <Pressable
            style={StyleSheet.absoluteFill}
            onPress={() => setPickerOpen(false)}
            accessibilityRole="button"
            accessibilityLabel={t('common.cancel')}
          />
          <View style={styles.dialog} accessibilityViewIsModal>
            <Text style={styles.dialogTitle}>{t('my.language')}</Text>
            <View style={styles.list}>
              {options.map((o) => (
                <ListRow
                  key={o.value}
                  icon={o.value === 'system' ? 'phone-portrait-outline' : 'language-outline'}
                  label={o.label}
                  selected={language === o.value}
                  onPress={() => choose(o.value)}
                />
              ))}
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  button: {
    width: 40,
    height: 40,
    borderRadius: theme.radius.pill,
    borderWidth: 1,
    borderColor: theme.colors.border,
    backgroundColor: theme.colors.card,
    alignItems: 'center',
    justifyContent: 'center',
  },
  pressed: { backgroundColor: theme.colors.surfaceAlt },
  badge: {
    position: 'absolute',
    top: -4,
    right: -4,
    minWidth: 18,
    height: 18,
    paddingHorizontal: 4,
    borderRadius: 9,
    backgroundColor: theme.colors.rose,
    alignItems: 'center',
    justifyContent: 'center',
  },
  badgeText: { fontSize: 11, fontWeight: '700', color: theme.colors.white },
  overlay: { flex: 1, backgroundColor: theme.colors.overlay, justifyContent: 'center', padding: theme.spacing.xl },
  dialog: { backgroundColor: theme.colors.card, borderRadius: theme.radius.lg, padding: theme.spacing.lg, gap: 12 },
  dialogTitle: { fontSize: theme.font.title, fontWeight: '800', color: theme.colors.ink },
  list: { borderRadius: theme.radius.md, overflow: 'hidden', borderWidth: 1, borderColor: theme.colors.border },
});
