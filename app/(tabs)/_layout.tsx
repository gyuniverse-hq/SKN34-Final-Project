import Ionicons from '@expo/vector-icons/Ionicons';
import { Tabs } from 'expo-router';
import type { ComponentProps } from 'react';
import type { ColorValue } from 'react-native';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';
import { selectCartCount, useCartStore } from '@/store/cartStore';

type IconName = ComponentProps<typeof Ionicons>['name'];

function icon(active: IconName, inactive: IconName) {
  function TabIcon({ color, focused }: { color: ColorValue; focused: boolean }) {
    return <Ionicons name={focused ? active : inactive} size={24} color={color as string} />;
  }
  return TabIcon;
}

export default function TabLayout() {
  const { t } = useI18n();
  const cartCount = useCartStore(selectCartCount);

  return (
    <Tabs
      screenOptions={{
        tabBarActiveTintColor: theme.colors.rose,
        tabBarInactiveTintColor: theme.colors.inkFaint,
        tabBarStyle: { backgroundColor: theme.colors.card, borderTopColor: theme.colors.border },
        headerStyle: { backgroundColor: theme.colors.surface },
        headerTitleStyle: { fontWeight: '800', color: theme.colors.ink },
        headerShadowVisible: false,
      }}>
      <Tabs.Screen
        name="index"
        options={{ title: t('tabs.shop'), headerShown: false, tabBarIcon: icon('bag-handle', 'bag-handle-outline') }}
      />
      <Tabs.Screen
        name="celeb"
        options={{ title: t('tabs.looks'), headerShown: false, tabBarIcon: icon('sparkles', 'sparkles-outline') }}
      />
      <Tabs.Screen
        name="ar"
        options={{ title: t('tabs.tryOn'), headerShown: false, tabBarIcon: icon('scan-circle', 'scan-circle-outline') }}
      />
      <Tabs.Screen
        name="cart"
        options={{
          title: t('tabs.cart'),
          tabBarIcon: icon('cart', 'cart-outline'),
          tabBarBadge: cartCount > 0 ? (cartCount > 99 ? '99+' : cartCount) : undefined,
          tabBarBadgeStyle: { backgroundColor: theme.colors.rose },
        }}
      />
      <Tabs.Screen
        name="my"
        options={{ title: t('tabs.my'), tabBarIcon: icon('person-circle', 'person-circle-outline') }}
      />
    </Tabs>
  );
}
