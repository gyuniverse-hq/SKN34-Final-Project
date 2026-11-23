import Ionicons from '@expo/vector-icons/Ionicons';
import { Tabs, useRouter } from 'expo-router';
import type { BottomTabBarButtonProps } from 'expo-router/js-tabs';
import { PlatformPressable } from 'expo-router/react-navigation';
import { useState, type ComponentProps } from 'react';
import { StyleSheet, Text, View, type ColorValue } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Svg, { Path } from 'react-native-svg';
import { HomeChatButton } from '@/components/chat/HomeChatButton';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';
import { chatHref } from '@/lib/routes';
import { useMakeupStore } from '@/store/makeupStore';

type IconName = ComponentProps<typeof Ionicons>['name'];
const TRY_ON_SIZE = 60;

function TabButton({ mirrorLabel, children, ...props }: BottomTabBarButtonProps & { mirrorLabel?: string }) {
  const [pressed, setPressed] = useState(false);
  const color = props['aria-selected'] ? theme.colors.rose : theme.colors.inkFaint;
  const feedback = pressed && (
    <View pointerEvents="none" aria-hidden style={[styles.pressOverlay, !!mirrorLabel && styles.roundOverlay]} />
  );
  return (
    <PlatformPressable {...props} android_ripple={{ color: 'transparent' }}
      onPressIn={event => { setPressed(true); props.onPressIn?.(event); }}
      onPressOut={event => { setPressed(false); props.onPressOut?.(event); }}>
      {mirrorLabel ? <View style={styles.tryOnCircle} aria-hidden pointerEvents="none">
        <Svg width={30} height={30} viewBox="0 0 28 28" fill="none" stroke={color}
          strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
          <Path d="M3 9V6a3 3 0 0 1 3-3h3m10 0h3a3 3 0 0 1 3 3v3M3 19v3a3 3 0 0 0 3 3h3m10 0h3a3 3 0 0 0 3-3v-3" />
          <Path d="M7.6 12c.1 4.6 2.2 7.7 6.1 9 3.8-1.2 6.1-4.5 6.4-9.1M8.7 10.2c3.6-.3 6.2-2 7.4-4.4.5 2 1.7 3.3 3.5 4.2" strokeWidth={1.65} />
          <Path d="M11.7 16.9q1.9 1.2 3.8 0" strokeWidth={1.45} />
        </Svg>
        <Text numberOfLines={1} style={[styles.tryOnLabel, { color }]}>{mirrorLabel}</Text>
        {feedback}
      </View> : <>{children}{feedback}</>}
    </PlatformPressable>
  );
}

function TabBarBackground() {
  return <View pointerEvents="none" style={styles.barSurface} />;
}

function icon(active: IconName, inactive: IconName) {
  function TabIcon({ color, focused }: { color: ColorValue; focused: boolean }) {
    return <Ionicons name={focused ? active : inactive} size={24} color={color as string} />;
  }
  return TabIcon;
}

export default function TabLayout() {
  const { t } = useI18n();
  const tryOnLabel = t('tabs.tryOn');
  const router = useRouter();
  const { bottom } = useSafeAreaInsets();

  return (
    <Tabs
      screenLayout={({ children, route }) => route.name === 'ar' ? children : (
        <View style={{ flex: 1 }}>
          {children}
          <HomeChatButton label={t('home.chatFab')} hint={t('home.chatFabHint')} onPress={() => router.push(chatHref())} />
        </View>
      )}
      screenOptions={{
        tabBarActiveTintColor: theme.colors.rose,
        tabBarInactiveTintColor: theme.colors.inkFaint,
        tabBarStyle: { height: 70 + bottom, borderTopWidth: 0, backgroundColor: theme.colors.surface },
        tabBarBackground: TabBarBackground,
        tabBarButton: props => <TabButton {...props} />,
        tabBarLabelPosition: 'below-icon',
        tabBarIconStyle: styles.standardIcon,
        tabBarItemStyle: styles.standardItem,
        headerStyle: { backgroundColor: theme.colors.surface },
        headerTitleStyle: { fontWeight: '800', color: theme.colors.ink },
        headerShadowVisible: false,
      }}>
      <Tabs.Screen
        name="index"
        options={{ title: t('tabs.home'), headerShown: false, tabBarIcon: icon('home', 'home-outline') }}
      />
      <Tabs.Screen
        name="celeb"
        options={{ title: t('tabs.looks'), headerShown: false, tabBarIcon: icon('sparkles', 'sparkles-outline') }}
      />
      <Tabs.Screen
        name="ar"
        listeners={({ navigation }) => ({
          tabPress: (event) => {
            const state = navigation.getState();
            if (state.routes[state.index]?.name !== 'index') return;

            // A direct home entry starts a fresh try-on, including when the AR tab
            // retains parameters from an earlier video or product visit.
            event.preventDefault();
            useMakeupStore.getState().reset();
            navigation.navigate('ar', {
              video: undefined, productId: undefined, shadeId: undefined, compare: undefined,
            }, { merge: false });
          },
        })}
        options={{
          title: tryOnLabel, headerShown: false, tabBarAccessibilityLabel: tryOnLabel,
          tabBarButton: props => <TabButton {...props} mirrorLabel={tryOnLabel} />,
          tabBarItemStyle: styles.centerItem,
        }}
      />
      <Tabs.Screen
        name="shop"
        options={{ title: t('tabs.products'), headerShown: false, tabBarIcon: icon('bag-handle', 'bag-handle-outline') }}
      />
      <Tabs.Screen
        name="my"
        options={{ title: t('tabs.my'), headerShown: false, tabBarIcon: icon('person-circle', 'person-circle-outline') }}
      />
    </Tabs>
  );
}

const styles = StyleSheet.create({
  barSurface: { position: 'absolute', top: 16, bottom: 0, left: 0, right: 0, backgroundColor: theme.colors.card,
    borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: theme.colors.border },
  standardItem: { paddingTop: 22 },
  standardIcon: { height: 26 },
  centerItem: { paddingTop: 0 },
  tryOnCircle: { width: TRY_ON_SIZE, height: TRY_ON_SIZE, borderRadius: TRY_ON_SIZE / 2,
    alignItems: 'center', justifyContent: 'center', gap: 1, backgroundColor: theme.colors.card,
    boxShadow: '0px 2px 3px rgba(51, 36, 45, 0.14)' },
  pressOverlay: { ...StyleSheet.absoluteFill, zIndex: 1, borderRadius: 10, backgroundColor: 'rgba(120, 44, 76, 0.12)' },
  roundOverlay: { borderRadius: TRY_ON_SIZE / 2 },
  tryOnLabel: { fontSize: 8, lineHeight: 11, letterSpacing: -0.24, fontWeight: '500' },
});
