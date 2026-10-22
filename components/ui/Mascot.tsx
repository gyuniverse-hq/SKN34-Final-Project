import { Image } from 'expo-image';
import { useEffect } from 'react';
import Animated, {
  cancelAnimation,
  Easing,
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withRepeat,
  withSequence,
  withTiming,
} from 'react-native-reanimated';

const SOURCE = require('@/assets/images/splash-icon.png');

interface Props {
  size?: number;
  /** Bigger hop with a squash on landing, for loading states. */
  bounce?: boolean;
  /** Hide from screen readers when the surrounding view already describes the state. */
  decorative?: boolean;
}

/** The VISHUE dog, breathing and tilting its head. Holds still when the system asks to reduce motion. */
export function Mascot({ size = 96, bounce = false, decorative = false }: Props) {
  const reduceMotion = useReducedMotion();
  const lift = useSharedValue(0);
  const tilt = useSharedValue(0);

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

  const animatedStyle = useAnimatedStyle(() => {
    const up = lift.get();
    const down = 1 - up;
    return {
      transform: bounce
        ? [
            { translateY: -up * size * 0.14 },
            { rotate: `${tilt.get() * 3}deg` },
            { scaleX: 1 + down * 0.05 },
            { scaleY: 1 - down * 0.06 },
          ]
        : [
            { translateY: -up * size * 0.03 },
            { rotate: `${tilt.get() * 4}deg` },
            { scale: 1 + up * 0.035 },
          ],
    };
  });

  return (
    <Animated.View
      style={[{ width: size, height: size, alignSelf: 'center' }, animatedStyle]}
      accessible={!decorative}
      accessibilityRole={decorative ? undefined : 'image'}
      accessibilityLabel={decorative ? undefined : 'VISHUE'}
      aria-hidden={decorative}>
      <Image source={SOURCE} style={{ width: size, height: size }} contentFit="contain" />
    </Animated.View>
  );
}
