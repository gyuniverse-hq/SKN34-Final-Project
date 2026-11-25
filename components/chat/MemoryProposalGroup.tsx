import { useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';
import type { ChatMemoryDecision, ChatMemoryProposalGroup, ChatMemoryProposalItem } from '@/types';

type Choice = { version: number; action: 'approve' | 'reject' };

export function MemoryProposalGroup({ group, busy, onEdit, onDecide }: {
  group: ChatMemoryProposalGroup;
  busy: boolean;
  onEdit: (item: ChatMemoryProposalItem, value: string) => Promise<boolean>;
  onDecide: (decisions: ChatMemoryDecision[]) => Promise<boolean>;
}) {
  const { t } = useI18n();
  const [choices, setChoices] = useState<Record<string, Choice>>({});
  const [editing, setEditing] = useState<{ itemId: string; version: number; value: string }>();
  const [expired, setExpired] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  useEffect(() => {
    const timeout = setTimeout(() => setExpired(true), Math.max(0, Date.parse(group.expiresAt) - Date.now()));
    return () => clearTimeout(timeout);
  }, [group.expiresAt]);

  if (dismissed) return null;
  if (expired) return <View style={styles.card}>
    <Text accessibilityRole="alert" style={styles.note}>{t('chat.memory.expired')}</Text>
    <Pressable accessibilityRole="button" onPress={() => setDismissed(true)} style={styles.button}>
      <Text style={styles.action}>{t('chat.memory.cancel')}</Text>
    </Pressable>
  </View>;

  const pick = (item: ChatMemoryProposalItem, action: Choice['action']) => {
    setChoices((current) => {
      const next = { ...current };
      if (next[item.itemId]?.version === item.version && next[item.itemId].action === action) delete next[item.itemId];
      else next[item.itemId] = { version: item.version, action };
      return next;
    });
  };
  const proposed = group.items.map((item) => {
    const choice = choices[item.itemId];
    return { item, action: choice?.version === item.version ? choice.action : 'defer' as const };
  });
  const hasDecisions = proposed.some(({ action }) => action !== 'defer');
  const hasEdit = !!editing && group.items.some((item) => item.itemId === editing.itemId && item.version === editing.version);
  const submit = async (deferAll: boolean) => {
    const decisions: ChatMemoryDecision[] = proposed.map(({ item, action }) => {
      const reference = { itemId: item.itemId, expectedVersion: item.version };
      if (deferAll) return { ...reference, action: 'defer' };
      return action === 'approve' ? { ...reference, action, confirmed: true } : { ...reference, action };
    });
    if (await onDecide(decisions)) {
      setChoices({});
      if (deferAll) setDismissed(true);
    }
  };

  return <View style={styles.card}>
    <Text accessibilityRole="header" style={styles.title}>{t('chat.memory.proposal')}</Text>
    <Text style={styles.note}>{t('chat.memory.selectItems')}</Text>
    {proposed.map(({ item, action }) => {
      const pendingEdit = editing?.itemId === item.itemId && editing.version === item.version ? editing : undefined;
      return <View key={item.itemId} style={styles.item}>
        <Text style={styles.label}>{t(item.kind === 'profile' ? 'chat.memory.profile'
          : item.kind === 'owned_product' ? 'chat.memory.ownedProduct' : 'chat.memory.preference')}</Text>
        {item.previousDisplayValue ? <Text style={styles.note}>
          {t('chat.memory.replaces', { previous: item.previousDisplayValue })}
        </Text> : null}
        <Text style={styles.title}>{item.displayValue}</Text>
        {pendingEdit ? <>
          {item.choices.length ? <View style={styles.actions}>
            {item.choices.map(([value, label]) => <Pressable key={value} accessibilityRole="button"
              accessibilityState={{ selected: pendingEdit.value === value }} aria-pressed={pendingEdit.value === value}
              disabled={busy}
              onPress={() => setEditing({ ...pendingEdit, value })}
              style={[styles.button, pendingEdit.value === value && styles.selected]}>
              <Text style={styles.action}>{label}</Text>
            </Pressable>)}
          </View> : <TextInput accessibilityLabel={t('chat.memory.edit')} value={pendingEdit.value}
            maxLength={500} editable={!busy} onChangeText={(value) => setEditing({ ...pendingEdit, value })}
            style={styles.input} />}
          <View style={styles.actions}>
            <Pressable accessibilityRole="button" disabled={busy || !pendingEdit.value.trim()}
              onPress={async () => {
                if (await onEdit(item, pendingEdit.value)) setEditing(undefined);
              }} style={styles.button}>
              <Text style={styles.action}>{t('chat.memory.saveEdit')}</Text>
            </Pressable>
            <Pressable accessibilityRole="button" disabled={busy} onPress={() => setEditing(undefined)}
              style={styles.button}><Text style={styles.action}>{t('chat.memory.cancel')}</Text></Pressable>
          </View>
        </> : <View style={styles.actions}>
          <Pressable accessibilityRole="checkbox" accessibilityLabel={item.displayValue}
            accessibilityState={{ checked: action === 'approve' }} aria-checked={action === 'approve'} disabled={busy}
            onPress={() => pick(item, 'approve')} style={[styles.button, action === 'approve' && styles.selected]}>
            <Text style={styles.action}>{action === 'approve' ? '✓ ' : ''}{t('chat.memory.select')}</Text>
          </Pressable>
          <Pressable accessibilityRole="button" accessibilityState={{ selected: action === 'reject' }}
            aria-pressed={action === 'reject'} disabled={busy}
            onPress={() => pick(item, 'reject')} style={[styles.button, action === 'reject' && styles.selected]}>
            <Text style={styles.action}>{t('chat.memory.reject')}</Text>
          </Pressable>
          <Pressable accessibilityRole="button" disabled={busy}
            onPress={() => setEditing({ itemId: item.itemId, version: item.version, value: item.editableValue })}
            style={styles.button}><Text style={styles.action}>{t('chat.memory.edit')}</Text></Pressable>
        </View>}
      </View>;
    })}
    <View style={styles.actions}>
      <Pressable accessibilityRole="button" disabled={busy || !hasDecisions || hasEdit}
        onPress={() => void submit(false)} style={[styles.button, (!hasDecisions || hasEdit) && styles.disabled]}>
        <Text style={styles.action}>{t('chat.memory.applyDecisions')}</Text>
      </Pressable>
      <Pressable accessibilityRole="button" disabled={busy || hasEdit} onPress={() => void submit(true)}
        style={styles.button}><Text style={styles.action}>{t('chat.memory.dismiss')}</Text></Pressable>
    </View>
  </View>;
}

const styles = StyleSheet.create({
  card: { gap: 8, padding: 12, borderWidth: 1, borderColor: theme.colors.border,
    borderRadius: theme.radius.md, backgroundColor: theme.colors.card },
  item: { gap: 5, paddingTop: 8, borderTopWidth: 1, borderColor: theme.colors.border },
  title: { color: theme.colors.ink, fontWeight: '700' },
  label: { color: theme.colors.roseDark, fontSize: theme.font.caption, fontWeight: '700' },
  note: { color: theme.colors.inkMuted, fontSize: theme.font.caption },
  actions: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  button: { minHeight: 44, justifyContent: 'center', paddingHorizontal: 10, borderRadius: theme.radius.md,
    borderWidth: 1, borderColor: theme.colors.border },
  selected: { backgroundColor: theme.colors.roseSoft, borderColor: theme.colors.roseDark },
  disabled: { opacity: 0.5 },
  action: { color: theme.colors.roseDark, fontWeight: '600' },
  input: { padding: 8, borderWidth: 1, borderColor: theme.colors.border, borderRadius: theme.radius.md,
    color: theme.colors.ink },
});
