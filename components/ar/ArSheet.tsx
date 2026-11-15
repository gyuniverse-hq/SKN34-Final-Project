import Ionicons from '@expo/vector-icons/Ionicons';
import type { ReactNode } from 'react';
import { Modal, Pressable, StyleSheet, Text, View } from 'react-native';
import { theme } from '@/constants/theme';

export function ArSheet({ title, closeLabel, bottomInset, onClose, children }: {
  title: string; closeLabel: string; bottomInset: number; onClose: () => void; children: ReactNode;
}) {
  return (
    <Modal transparent animationType="slide" onRequestClose={onClose} statusBarTranslucent>
      <View style={styles.scrim}>
        <Pressable style={StyleSheet.absoluteFill} accessibilityRole="button" accessibilityLabel={closeLabel} onPress={onClose} />
        <View style={[styles.sheet, { paddingBottom: Math.max(12, bottomInset) }]} accessibilityViewIsModal>
          <View style={styles.handle} />
          <View style={styles.header}>
            <Text style={styles.title} accessibilityRole="header">{title}</Text>
            <Pressable accessibilityRole="button" accessibilityLabel={closeLabel} onPress={onClose} style={styles.close}>
              <Ionicons name="close" size={22} color={theme.colors.ink} />
            </Pressable>
          </View>
          {children}
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  scrim: { flex: 1, justifyContent: 'flex-end', backgroundColor: 'rgba(20,12,16,0.35)' },
  sheet: { maxHeight: '78%', backgroundColor: theme.colors.surface, borderTopLeftRadius: 26, borderTopRightRadius: 26, paddingTop: 8 },
  handle: { width: 32, height: 4, borderRadius: 2, backgroundColor: theme.colors.border, alignSelf: 'center' },
  header: { paddingLeft: 20, paddingRight: 10, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  title: { color: theme.colors.ink, fontSize: 16, fontWeight: '700' },
  close: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
});
