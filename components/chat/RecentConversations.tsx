import Ionicons from '@expo/vector-icons/Ionicons';
import { useState, type ReactNode } from 'react';
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { theme } from '@/constants/theme';
import { confirmAction } from '@/lib/confirm';
import { useI18n } from '@/lib/i18n';
import type { ConversationRecord } from '@/store/chatConversationStore';

const labels = { general: 'chat.room.general', look: 'chat.room.look', product: 'chat.room.product' } as const;
const icons = { general: 'chatbubble-outline', look: 'color-palette-outline', product: 'bag-outline' } as const;
const summaryTitles = { look: labels.look, product: labels.product, ingredient: 'chat.ui.ingredient' } as const;
const summaryTopics = { hydration: 'careTag.hydrating', price: 'chat.option.price' } as const;

export function RecentConversations({ rooms, activeId, renderSubject, onClose, onNew, onSelect, canDelete, onDelete, loading, error, hasMore, onMore, onRefresh }: {
  rooms: ConversationRecord[];
  activeId: string;
  renderSubject: (room: ConversationRecord) => ReactNode;
  onClose: () => void;
  onNew: () => void;
  onSelect: (id: string) => void;
  canDelete: (room: ConversationRecord['conversation']) => boolean;
  onDelete: (id: string) => void;
  loading?: boolean;
  error?: boolean;
  hasMore?: boolean;
  onMore?: () => void;
  onRefresh?: () => void;
}) {
  const { t, language } = useI18n();
  const [openedAt] = useState(Date.now);
  const recent = rooms.filter(({ conversation, messages }) => conversation.serverId || messages.some((item) => !item.automatic && item.role === 'user' ||
    item.role === 'assistant' && item.styleRecipe)).sort((a, b) => b.updatedAt - a.updatedAt);
  return <Modal animationType="slide" onRequestClose={onClose} presentationStyle="pageSheet">
    <SafeAreaView style={styles.panel} accessibilityViewIsModal>
      <View style={styles.header}>
        <Text accessibilityRole="header" style={styles.title}>{t('chat.room.recent')}</Text>
        <View style={styles.actions}>
          {onRefresh ? <Pressable accessibilityRole="button" accessibilityLabel={t('chat.room.refresh')}
            accessibilityState={{ disabled: !!loading }} disabled={loading} onPress={onRefresh} style={styles.close}>
            <Ionicons name="refresh" size={22} color={loading ? theme.colors.inkMuted : theme.colors.roseDark} />
          </Pressable> : null}
          <Pressable accessibilityRole="button" accessibilityLabel={t('common.cancel')} onPress={onClose} style={styles.close}>
            <Ionicons name="close" size={24} color={theme.colors.roseDark} />
          </Pressable>
        </View>
      </View>
      <ScrollView contentContainerStyle={styles.list}>
        <Pressable accessibilityRole="button" onPress={onNew} style={styles.row}>
          <Ionicons name="add" size={20} color={theme.colors.roseDark} />
          <Text style={styles.kind}>{t('chat.session.newConversation')}</Text>
        </Pressable>
        {loading ? <Text style={styles.secondary}>{t('chat.room.loading')}</Text> : null}
        {error ? <Text accessibilityRole="alert" style={styles.secondary}>{t('chat.room.loadError')}</Text> : null}
        {!recent.length && !loading && !error ? <Text style={styles.secondary}>{t('chat.room.empty')}</Text> : null}
        {recent.map((room) => {
          const { id, subject, deletionState, userId } = room.conversation;
          const last = room.messages.findLast((item) => item.role === 'user' && !item.automatic)
            ?? room.messages.findLast((item) => item.role === 'assistant');
          const expired = room.view.notice === 'chat.session.expired' ||
            (room.view.sessionExpiry != null && room.view.sessionExpiry * 1000 <= openedAt);
          const updatedAt = new Date(room.updatedAt).toLocaleString(language);
          const useSummary = subject.type === 'general' && !!userId;
          const summary = useSummary ? room.listSummary : undefined;
          const titleTopic = summary?.titleTopic;
          const kind = t(titleTopic && Object.hasOwn(summaryTitles, titleTopic) ? summaryTitles[titleTopic] : labels[subject.type]);
          const preview = useSummary
            ? (Array.isArray(summary?.previewTopics) ? summary.previewTopics : [])
              .filter((topic) => Object.hasOwn(summaryTopics, topic)).map((topic) => t(summaryTopics[topic])).join(' · ')
            : last?.text;
          const deleteAvailable = canDelete(room.conversation);
          return <View key={id} style={[styles.room, id === activeId && styles.selected]}>
            {!room.recoveredDeletion ? <View style={styles.roomHeader}>
              <Pressable accessibilityRole="button" disabled={!!deletionState}
                accessibilityState={{ selected: id === activeId, disabled: !!deletionState }}
                onPress={() => onSelect(id)} style={styles.roomInfo}>
                <Ionicons name={icons[subject.type]} size={20} color={theme.colors.roseDark} />
                <View style={styles.details}>
                  <Text style={styles.kind}>{kind}</Text>
                  {deletionState ? null : renderSubject(room)}
                  {!deletionState && preview ? <Text style={styles.preview} numberOfLines={2}>{preview}</Text> : null}
                  <Text style={styles.secondary}>{updatedAt}</Text>
                  {!deletionState && expired ? <Text style={styles.secondary}>{t('chat.room.expired')}</Text> : null}
                </View>
              </Pressable>
              {!deletionState && deleteAvailable ? <Pressable accessibilityRole="button"
                accessibilityLabel={t('common.delete')} accessibilityHint={preview || `${kind} · ${updatedAt}`}
                onPress={() => confirmAction(t('chat.room.deleteConfirm'), t('common.delete'), t('common.cancel'), () => onDelete(id))}
                style={styles.close}>
                <Ionicons name="trash-outline" size={20} color={theme.colors.danger} />
              </Pressable> : null}
            </View> : null}
            {deletionState ? <View style={[styles.deletion, room.recoveredDeletion && styles.recoveredDeletion]}>
              <Text accessibilityRole={deletionState === 'failed' ? 'alert' : undefined} accessibilityLiveRegion="polite"
                style={styles.secondary}>{t(deletionState === 'pending' ? 'chat.room.deleting' : 'chat.room.deleteError')}</Text>
              {deletionState === 'failed' ? <Pressable accessibilityRole="button" style={styles.retry} onPress={() => onDelete(id)}>
                <Text style={styles.kind}>{t('common.retry')}</Text>
              </Pressable> : null}
            </View> : !deleteAvailable ? <Text style={[styles.secondary, styles.deletion]}>
              {t('chat.room.deleteUnavailable')}
            </Text> : null}
          </View>;
        })}
        {hasMore && onMore ? <Pressable accessibilityRole="button" disabled={loading} onPress={onMore} style={styles.row}>
          <Text style={styles.kind}>{t('chat.room.more')}</Text>
        </Pressable> : null}
      </ScrollView>
    </SafeAreaView>
  </Modal>;
}

const styles = StyleSheet.create({
  panel: { flex: 1, backgroundColor: theme.colors.surface },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 20 },
  title: { color: theme.colors.ink, fontSize: theme.font.h2, fontWeight: '800' },
  actions: { flexDirection: 'row' },
  close: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  list: { padding: 16, gap: 10 },
  row: { flexDirection: 'row', alignItems: 'flex-start', gap: 12, padding: 14, borderRadius: theme.radius.md,
    backgroundColor: theme.colors.card, borderColor: theme.colors.border, borderWidth: 1 },
  room: { borderRadius: theme.radius.md, backgroundColor: theme.colors.card, borderColor: theme.colors.border, borderWidth: 1 },
  roomHeader: { flexDirection: 'row', alignItems: 'center', paddingRight: 8 },
  roomInfo: { flex: 1, flexDirection: 'row', alignItems: 'flex-start', gap: 12, padding: 14 },
  deletion: { paddingHorizontal: 14, paddingBottom: 12 },
  recoveredDeletion: { paddingTop: 12 },
  retry: { minHeight: 44, justifyContent: 'center', alignSelf: 'flex-start' },
  selected: { backgroundColor: theme.colors.roseSoft },
  details: { flex: 1, gap: 4 },
  kind: { color: theme.colors.roseDark, fontSize: theme.font.caption, fontWeight: '700' },
  preview: { color: theme.colors.ink, fontSize: theme.font.body },
  secondary: { color: theme.colors.inkMuted, fontSize: theme.font.caption },
});
