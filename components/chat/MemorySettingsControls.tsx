import { Pressable, StyleSheet, Text, View } from 'react-native';
import { theme } from '@/constants/theme';
import { confirmAction } from '@/lib/confirm';
import { useI18n } from '@/lib/i18n';
import type { ChatMemorySettings } from '@/types';

export function MemorySettingsControls({ settings, busy, showManagement, onChange, onDeleteAll }: {
  settings: ChatMemorySettings;
  busy: boolean;
  showManagement: boolean;
  onChange: (enabled: boolean | undefined, acknowledgeNotice?: true) => void;
  onDeleteAll: () => void;
}) {
  const { t } = useI18n();
  return <View style={styles.panel}>
    {!settings.noticeAcknowledged ? <>
      <Text accessibilityRole="header" style={styles.title}>{t('chat.memory.settings')}</Text>
      <Text style={styles.detail}>{t('chat.memory.firstNotice')}</Text>
      <View style={styles.actions}>
        <Pressable accessibilityRole="button" disabled={busy} style={styles.button}
          onPress={() => onChange(undefined, true)}>
          <Text style={styles.action}>{t('chat.memory.noticeConfirm')}</Text>
        </Pressable>
        {settings.enabled ? <Pressable accessibilityRole="button" disabled={busy} style={styles.button}
          onPress={() => onChange(false, true)}>
          <Text style={styles.action}>{t('chat.memory.turnOff')}</Text>
        </Pressable> : null}
      </View>
    </> : null}
    {showManagement ? <>
      <Pressable accessibilityRole="switch" accessibilityLabel={t('chat.memory.settings')}
        accessibilityState={{ checked: settings.enabled }} aria-checked={settings.enabled}
        disabled={busy} style={styles.button} onPress={() => onChange(!settings.enabled)}>
        <Text style={styles.action}>{t(settings.enabled ? 'chat.memory.statusOn' : 'chat.memory.statusOff')}</Text>
      </Pressable>
      {!settings.enabled ? <Text style={styles.detail}>{t('chat.memory.offDetail')}</Text> : null}
      <Pressable accessibilityRole="button" disabled={busy} style={styles.button}
        onPress={() => confirmAction(t('chat.memory.deleteAllConfirm'), t('chat.memory.deleteAll'),
          t('chat.memory.cancel'), onDeleteAll)}>
        <Text style={styles.danger}>{t('chat.memory.deleteAll')}</Text>
      </Pressable>
    </> : null}
  </View>;
}

const styles = StyleSheet.create({
  panel: { gap: 8, padding: 12, backgroundColor: theme.colors.card, borderRadius: theme.radius.md,
    borderWidth: 1, borderColor: theme.colors.border },
  title: { color: theme.colors.ink, fontWeight: '700' },
  detail: { color: theme.colors.inkMuted, fontSize: theme.font.caption },
  actions: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  button: { borderWidth: 1, borderColor: theme.colors.border, borderRadius: theme.radius.md,
    minHeight: 44, justifyContent: 'center', paddingHorizontal: 10 },
  action: { color: theme.colors.roseDark, fontWeight: '600' },
  danger: { color: theme.colors.danger, fontWeight: '600' },
});
