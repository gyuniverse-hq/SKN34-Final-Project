import Ionicons from '@expo/vector-icons/Ionicons';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useEffect, useRef, useState } from 'react';
import { Keyboard, Platform, Pressable, StyleSheet, Text, View, type GestureResponderEvent } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { create } from 'zustand';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';

type Position = { x: number; y: number };
const BUTTON_SIZE = 58;
const MARGIN = 18;
const STORAGE_KEY = 'vishue.chat.fab-position.v1';
const defaultPosition = { x: 1, y: 1 };
const usePosition = create<{ position: Position }>(() => ({ position: defaultPosition }));
let hydration: Promise<void> | undefined;
let savedLocally = false;
let writes = Promise.resolve();
const clamp = (value: number) => Math.min(1, Math.max(0, value));

function restorePosition() {
  hydration ??= AsyncStorage.getItem(STORAGE_KEY).then((stored) => {
    if (!stored || savedLocally) return;
    const position: Position | null = JSON.parse(stored);
    if (position && Number.isFinite(position.x) && Number.isFinite(position.y)) {
      usePosition.setState({ position: { x: clamp(position.x), y: clamp(position.y) } });
    }
  }).catch(() => {});
  return hydration;
}

function savePosition(position: Position) {
  savedLocally = true;
  usePosition.setState({ position });
  writes = writes.then(() => AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(position))).catch(() => {});
}

export function HomeChatButton({ label, hint, onPress }: {
  label: string; hint: string; onPress: () => void;
}) {
  const { t } = useI18n();
  const position = usePosition((state) => state.position);
  const [area, setArea] = useState({ width: 0, height: 0 });
  const [preview, setPreview] = useState<Position>();
  const [keyboardVisible, setKeyboardVisible] = useState(false);
  const [showReset, setShowReset] = useState(false);
  const touch = useRef<{ pageX: number; pageY: number; position: Position; moved?: Position } | null>(null);
  const armed = useRef(false);
  const suppressPress = useRef(false);

  useEffect(() => { void restorePosition(); }, []);
  useEffect(() => {
    const show = Keyboard.addListener(Platform.OS === 'ios' ? 'keyboardWillShow' : 'keyboardDidShow',
      () => setKeyboardVisible(true));
    const hide = Keyboard.addListener(Platform.OS === 'ios' ? 'keyboardWillHide' : 'keyboardDidHide',
      () => setKeyboardVisible(false));
    return () => { show.remove(); hide.remove(); };
  }, []);

  const range = { x: Math.max(0, area.width - BUTTON_SIZE - 2 * MARGIN), y: Math.max(0, area.height - BUTTON_SIZE - 2 * MARGIN) };
  const display = preview ?? position;
  const offset = area.width > 0 && area.height > 0 ? {
    left: MARGIN + display.x * range.x, top: MARGIN + display.y * range.y, right: undefined, bottom: undefined,
  } : undefined;
  const reset = () => {
    setShowReset(false);
    setPreview(undefined);
    savePosition(defaultPosition);
  };
  const move = ({ nativeEvent }: GestureResponderEvent) => {
    const start = touch.current;
    if (!armed.current || !start || nativeEvent.touches.length !== 1) return;
    const dx = nativeEvent.pageX - start.pageX, dy = nativeEvent.pageY - start.pageY;
    if (!start.moved && Math.hypot(dx, dy) < 4) return;
    const next = {
      x: range.x ? clamp(start.position.x + dx / range.x) : start.position.x,
      y: range.y ? clamp(start.position.y + dy / range.y) : start.position.y,
    };
    start.moved = next;
    setPreview(next);
  };
  const finish = (cancelled: boolean) => {
    if (armed.current && !cancelled) {
      const moved = touch.current?.moved;
      if (moved) {
        savePosition(moved);
        setShowReset(false);
      } else setShowReset((visible) => !visible);
    }
    armed.current = false;
    touch.current = null;
    setPreview(undefined);
  };

  if (keyboardVisible) return null;
  return (
    <SafeAreaView pointerEvents="box-none" edges={['top', 'left', 'right']} style={styles.safe}>
      <View pointerEvents="box-none" style={styles.area}
        onLayout={({ nativeEvent }) => {
          const { width, height } = nativeEvent.layout;
          setArea({ width, height });
        }}>
        {showReset ? <Pressable accessibilityRole="button" onPress={reset} style={[styles.reset, display.x < 0.5 && { left: undefined, right: 16 }]}>
          <Text style={styles.resetText}>{t('home.chatFabReset')}</Text>
        </Pressable> : null}
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={label}
          accessibilityHint={`${hint} ${t('home.chatFabMoveHint')}`}
          accessibilityActions={[{ name: 'resetPosition', label: t('home.chatFabReset') }]}
          onAccessibilityAction={(event) => { if (event.nativeEvent.actionName === 'resetPosition') reset(); }}
          hitSlop={8}
          delayLongPress={380}
          onTouchStart={({ nativeEvent }) => {
            armed.current = false;
            suppressPress.current = false;
            touch.current = { pageX: nativeEvent.pageX, pageY: nativeEvent.pageY, position };
          }}
          onLongPress={() => { armed.current = true; suppressPress.current = true; }}
          onTouchMove={move}
          onTouchEnd={() => finish(false)}
          onTouchCancel={() => finish(true)}
          onPress={() => {
            if (suppressPress.current) { suppressPress.current = false; return; }
            setShowReset(false);
            onPress();
          }}
          style={({ pressed }) => [styles.button, offset, pressed && !preview && styles.pressed]}>
          <Ionicons name="chatbubble-ellipses" size={24} color={theme.colors.white} />
          <View style={styles.badge} pointerEvents="none">
            <Text style={styles.badgeText}>AI</Text>
          </View>
        </Pressable>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { position: 'absolute', top: 0, right: 0, bottom: 0, left: 0, zIndex: 20 },
  area: { flex: 1 },
  reset: { position: 'absolute', left: 16, bottom: 16, minHeight: 44, justifyContent: 'center',
    borderRadius: 22, paddingHorizontal: 14, backgroundColor: theme.colors.card,
    borderWidth: 1, borderColor: theme.colors.border },
  resetText: { color: theme.colors.roseDark, fontWeight: '700' },
  button: {
    alignItems: 'center',
    backgroundColor: theme.colors.rose,
    borderColor: theme.colors.white,
    borderRadius: 29,
    borderWidth: 3,
    bottom: 20,
    elevation: 6,
    height: 58,
    justifyContent: 'center',
    position: 'absolute',
    right: 18,
    shadowColor: theme.colors.roseDark,
    shadowOffset: { width: 0, height: 5 },
    shadowOpacity: 0.28,
    shadowRadius: 8,
    width: 58,
  },
  badge: {
    alignItems: 'center',
    backgroundColor: theme.colors.accent,
    borderColor: theme.colors.white,
    borderRadius: 10,
    borderWidth: 1.5,
    height: 20,
    justifyContent: 'center',
    position: 'absolute',
    right: -3,
    top: -3,
    width: 24,
  },
  badgeText: { color: theme.colors.white, fontSize: 9, fontWeight: '900', letterSpacing: 0.2 },
  pressed: { opacity: 0.88, transform: [{ scale: 0.96 }] },
});
