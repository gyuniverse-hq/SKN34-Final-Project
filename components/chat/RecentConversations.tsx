import Ionicons from '@expo/vector-icons/Ionicons';
import { useState, type ReactNode } from 'react';
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';
import type { ConversationRecord } from '@/store/chatConversationStore';

const labels = { general: 'chat.room.general', look: 'chat.room.look', product: 'chat.room.product' } as const;
const icons = { general: 'chatbubble-outline', look: 'color-palette-outline', product: 'bag-outline' } as const;

export function RecentConversations({ rooms, activeId, renderSubject, onClose, onNew, onSelect }: {
  rooms: ConversationRecord[];
  activeId: string;
  renderSubject: (room: ConversationRecord) => ReactNode;
  onClose: () => void;
  onNew: () => void;
  onSelect: (id: string) => void;
}) {
  const { t, language } = useI18n();
  const [openedAt] = useState(Date.now);
  const recent = rooms.filter(({ messages }) => messages.some((item) => !item.automatic && item.role === 'user' ||
    item.role === 'assistant' && item.styleRecipe)).sort((a, b) => b.updatedAt - a.updatedAt);
  return <Modal animationType="slide" onRequestClose={onClose} presentationStyle="pageSheet">
    <SafeAreaView style={styles.panel} accessibilityViewIsModal>
      <View style={styles.header}>
        <Text accessibilityRole="header" style={styles.title}>{t('chat.room.recent')}</Text>
        <Pressable accessibilityRole="button" accessibilityLabel={t('common.cancel')} onPress={onClose} style={styles.close}>
          <Ionicons name="close" size={24} color={theme.colors.roseDark} />
        </Pressable>
      </View>
      <ScrollView contentContainerStyle={styles.list}>
        <Pressable accessibilityRole="button" onPress={onNew} style={styles.row}>
          <Ionicons name="add" size={20} color={theme.colors.roseDark} />
          <Text style={styles.kind}>{t('chat.session.newConversation')}</Text>
        </Pressable>
        {!recent.length ? <Text style={styles.secondary}>{t('chat.room.empty')}</Text> : null}
        {recent.map((room) => {
          const { id, subject } = room.conversation;
          const last = room.messages.findLast((item) => item.role === 'user' && !item.automatic)
            ?? room.messages.findLast((item) => item.role === 'assistant');
          const expired = room.view.notice === 'chat.session.expired' ||
            (room.view.sessionExpiry != null && room.view.sessionExpiry * 1000 <= openedAt);
          return <Pressable key={id} accessibilityRole="button" accessibilityState={{ selected: id === activeId }}
            onPress={() => onSelect(id)} style={[styles.row, id === activeId && styles.selected]}>
            <Ionicons name={icons[subject.type]} size={20} color={theme.colors.roseDark} />
            <View style={styles.details}>
              <Text style={styles.kind}>{t(labels[subject.type])}</Text>
              {renderSubject(room)}
              <Text style={styles.preview} numberOfLines={2}>{last?.text}</Text>
              <Text style={styles.secondary}>{new Date(room.updatedAt).toLocaleString(language)}</Text>
              {expired ? <Text style={styles.secondary}>{t('chat.room.expired')}</Text> : null}
            </View>
          </Pressable>;
        })}
      </ScrollView>
    </SafeAreaView>
  </Modal>;
}

const styles = StyleSheet.create({
  panel: { flex: 1, backgroundColor: theme.colors.surface },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 20 },
  title: { color: theme.colors.ink, fontSize: theme.font.h2, fontWeight: '800' },
  close: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  list: { padding: 16, gap: 10 },
  row: { flexDirection: 'row', alignItems: 'flex-start', gap: 12, padding: 14, borderRadius: theme.radius.md,
    backgroundColor: theme.colors.card, borderColor: theme.colors.border, borderWidth: 1 },
  selected: { backgroundColor: theme.colors.roseSoft },
  details: { flex: 1, gap: 4 },
  kind: { color: theme.colors.roseDark, fontSize: theme.font.caption, fontWeight: '700' },
  preview: { color: theme.colors.ink, fontSize: theme.font.body },
  secondary: { color: theme.colors.inkMuted, fontSize: theme.font.caption },
});
