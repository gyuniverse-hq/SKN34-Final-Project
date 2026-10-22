import Ionicons from '@expo/vector-icons/Ionicons';
import { Image } from 'expo-image';
import * as Haptics from 'expo-haptics';
import { useEffect, useRef, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import Animated, {
  cancelAnimation,
  Easing,
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withDelay,
  withRepeat,
  withSequence,
  withSpring,
  withTiming,
} from 'react-native-reanimated';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';

const SOURCE = require('@/assets/images/splash-icon.png');

const BUBBLE_MS = 2000;
const HEART_TAPS = 5;
const TAP_WINDOW_MS = 600;
const HEART_COUNT = 7;
const HEART_MS = 1000;
const BUBBLE_WIDTH = 200;

interface Props {
  size?: number;
  /** Bigger hop with a squash on landing, for loading states. */
  bounce?: boolean;
  /** Hide from screen readers when the surrounding view already describes the state. */
  decorative?: boolean;
  /** Makes the mascot tappable: it jumps and says this line. Five quick taps release hearts. */
  speech?: string;
}

interface HeartSpec {
  id: number;
  dx: number;
  rise: number;
  delay: number;
}

function Heart({ spec, size, reduceMotion }: { spec: HeartSpec; size: number; reduceMotion: boolean }) {
  const progress = useSharedValue(0);

  useEffect(() => {
    progress.set(withDelay(spec.delay, withTiming(1, { duration: HEART_MS - spec.delay, easing: Easing.out(Easing.quad) })));
  }, [progress, spec.delay]);

  const style = useAnimatedStyle(() => {
    const p = progress.get();
    const travel = reduceMotion ? 0 : 1;
    return {
      opacity: p === 0 ? 0 : p < 0.15 ? p / 0.15 : 1 - (p - 0.15) / 0.85,
      transform: [
        { translateX: spec.dx * p * travel },
        { translateY: -spec.rise * p * travel },
        { scale: 0.6 + 0.6 * p },
      ],
    };
  });

  return (
    <Animated.View pointerEvents="none" style={[styles.heart, { top: size * 0.3 }, style]}>
      <Ionicons name="heart" size={Math.round(size * 0.22)} color={theme.colors.rose} />
    </Animated.View>
  );
}

/** The VISHUE dog, breathing and tilting its head. Holds still when the system asks to reduce motion. */
export function Mascot({ size = 96, bounce = false, decorative = false, speech }: Props) {
  const { t } = useI18n();
  const reduceMotion = useReducedMotion();
  const lift = useSharedValue(0);
  const tilt = useSharedValue(0);
  const hop = useSharedValue(0);
  const [bubble, setBubble] = useState(false);
  const [hearts, setHearts] = useState<HeartSpec[]>([]);
  const taps = useRef({ count: 0, last: 0, nextId: 0 });
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => {
    if (reduceMotion) return;
    lift.set(
      withRepeat(
        withTiming(1, { duration: bounce ? 420 : 1400, easing: Easing.inOut(Easing.quad) }),
        -1,
        true
      )
    );
    tilt.set(
      withRepeat(
        withSequence(
          withTiming(-1, { duration: 900, easing: Easing.inOut(Easing.sin) }),
          withTiming(1, { duration: 1800, easing: Easing.inOut(Easing.sin) }),
          withTiming(0, { duration: 900, easing: Easing.inOut(Easing.sin) })
        ),
        -1
      )
    );
    return () => {
      cancelAnimation(lift);
      cancelAnimation(tilt);
    };
  }, [reduceMotion, bounce, lift, tilt]);

  useEffect(() => {
    const pending = timers.current;
    return () => pending.forEach(clearTimeout);
  }, []);

  const later = (fn: () => void, ms: number) => {
    timers.current.push(setTimeout(fn, ms));
  };

  const animatedStyle = useAnimatedStyle(() => {
    const up = lift.get();
    const down = 1 - up;
    const jump = -hop.get() * size * 0.28;
    return {
      transform: bounce
        ? [
            { translateY: -up * size * 0.14 + jump },
            { rotate: `${tilt.get() * 3}deg` },
            { scaleX: 1 + down * 0.05 },
            { scaleY: 1 - down * 0.06 },
          ]
        : [
            { translateY: -up * size * 0.03 + jump },
            { rotate: `${tilt.get() * 4}deg` },
            { scale: 1 + up * 0.035 },
          ],
    };
  });

  const releaseHearts = () => {
    const batch: HeartSpec[] = Array.from({ length: HEART_COUNT }, (_, i) => ({
      id: taps.current.nextId++,
      dx: (Math.random() - 0.5) * size * 1.4,
      rise: size * (0.6 + Math.random() * 0.6),
      delay: i * 60,
    }));
    setHearts((current) => [...current, ...batch]);
    const ids = new Set(batch.map((h) => h.id));
    later(() => setHearts((current) => current.filter((h) => !ids.has(h.id))), HEART_MS + 100);
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
  };

  const onPress = () => {
    const now = Date.now();
    const state = taps.current;
    state.count = now - state.last < TAP_WINDOW_MS ? state.count + 1 : 1;
    state.last = now;

    if (!reduceMotion) {
      hop.set(
        withSequence(
          withTiming(1, { duration: 160, easing: Easing.out(Easing.quad) }),
          withSpring(0, { damping: 7, stiffness: 180 })
        )
      );
    }
    setBubble(true);
    later(() => setBubble(false), BUBBLE_MS);

    if (state.count >= HEART_TAPS) {
      state.count = 0;
      releaseHearts();
    } else {
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
    }
  };

  const figure = (
    <Animated.View style={[{ width: size, height: size }, animatedStyle]}>
      <Image source={SOURCE} style={{ width: size, height: size }} contentFit="contain" />
    </Animated.View>
  );

  if (!speech) {
    return (
      <View
        style={[styles.frame, { width: size, height: size }]}
        accessible={!decorative}
        accessibilityRole={decorative ? undefined : 'image'}
        accessibilityLabel={decorative ? undefined : 'VISHUE'}
        aria-hidden={decorative}>
        {figure}
      </View>
    );
  }

  return (
    <View style={[styles.frame, { width: size, height: size }]}>
      {bubble ? (
        <View style={[styles.bubble, { bottom: size + 6, left: (size - BUBBLE_WIDTH) / 2 }]} pointerEvents="none">
          <Text style={styles.bubbleText} accessibilityLiveRegion="polite">
            {speech}
          </Text>
          <View style={styles.bubbleTail} />
        </View>
      ) : null}
      <Pressable
        onPress={onPress}
        accessibilityRole="button"
        accessibilityLabel="VISHUE"
        accessibilityHint={t('mascot.tapHint')}>
        {figure}
      </Pressable>
      {hearts.map((h) => (
        <Heart key={h.id} spec={h} size={size} reduceMotion={reduceMotion} />
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  frame: { alignSelf: 'center' },
  bubble: {
    position: 'absolute',
    width: BUBBLE_WIDTH,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: theme.radius.md,
    backgroundColor: theme.colors.card,
    borderWidth: 1,
    borderColor: theme.colors.border,
    ...theme.shadow,
  },
  bubbleText: { fontSize: theme.font.small, fontWeight: '600', color: theme.colors.ink, textAlign: 'center' },
  bubbleTail: {
    position: 'absolute',
    bottom: -6,
    left: BUBBLE_WIDTH / 2 - 6,
    width: 12,
    height: 12,
    backgroundColor: theme.colors.card,
    borderRightWidth: 1,
    borderBottomWidth: 1,
    borderColor: theme.colors.border,
    transform: [{ rotate: '45deg' }],
  },
  heart: { position: 'absolute', alignSelf: 'center' },
});
