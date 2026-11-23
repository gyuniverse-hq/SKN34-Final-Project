import Ionicons from '@expo/vector-icons/Ionicons';
import { useRef, useState, type ComponentRef } from 'react';
import { Modal, Pressable, ScrollView, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';
import type { Texture } from '@/types';

export function TextureSelect({ options, value, onChange }: {
  options: readonly Texture[]; value: Texture | null; onChange: (value: Texture | null) => void;
}) {
  const { t } = useI18n();
  const { height, width } = useWindowDimensions();
  const insets = useSafeAreaInsets();
  const trigger = useRef<ComponentRef<typeof View>>(null);
  const [anchor, setAnchor] = useState<{ top: number; right: number; width: number; height: number } | null>(null);
  const open = anchor?.height === height && anchor?.width === width;
  const close = () => setAnchor(null);
  const label = (tx: Texture | null) => tx ? t(`ar.texture.${tx}`) : t('ar.filter.all');
  return <View testID="ar-texture-anchor" ref={trigger} collapsable={false}>
    <Pressable accessibilityRole="button" accessibilityLabel={t('ar.textureLabel')} accessibilityValue={{ text: label(value) }}
      accessibilityState={{ expanded: open }} style={[styles.trigger, value && { backgroundColor: theme.colors.rose }]}
      onPress={() => trigger.current?.measureInWindow((x, y, w, h) => {
        setAnchor({ top: y + h, right: Math.max(8, width - x - w), width, height });
      })}>
      <Text style={styles.label}>{value ? label(value) : t('ar.textureLabel')}</Text>
      <Ionicons name="chevron-down" size={14} color="white" />
    </Pressable>
    {open && anchor ? <Modal visible transparent animationType="none" statusBarTranslucent onRequestClose={close}>
      <View style={{ flex: 1 }}>
        <Pressable style={StyleSheet.absoluteFill} accessibilityRole="button" accessibilityLabel={t('common.cancel')} onPress={close} />
        <ScrollView style={[styles.menu, { top: anchor.top, right: anchor.right, maxHeight: height - anchor.top - insets.bottom - 4 }]} accessibilityViewIsModal>
          {([null, ...options] as const).map(tx => <Pressable key={tx ?? 'all'} accessibilityRole="radio" accessibilityLabel={label(tx)} accessibilityState={{ checked: value === tx }}
            style={[styles.option, tx === value && { backgroundColor: theme.colors.rose }]} onPress={() => { onChange(tx); close(); }}>
            <Text style={styles.label}>{label(tx)}</Text>
          </Pressable>)}
        </ScrollView>
      </View>
    </Modal> : null}
  </View>;
}
const styles = StyleSheet.create({
  trigger: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', minHeight: 44, gap: 4, paddingHorizontal: 10, borderRadius: 22, backgroundColor: theme.colors.overlay },
  menu: { position: 'absolute', minWidth: 96, borderRadius: 12, backgroundColor: '#392E35' },
  option: { minHeight: 44, justifyContent: 'center', paddingHorizontal: 12 },
  label: { color: 'white', fontSize: 13, fontWeight: '600' },
});
