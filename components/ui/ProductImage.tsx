import Ionicons from '@expo/vector-icons/Ionicons';
import { Image } from 'expo-image';
import { useState, type ComponentProps } from 'react';
import { StyleSheet, Text, View, type ImageStyle, type StyleProp, type ViewStyle } from 'react-native';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';
import type { ProductCategory } from '@/types';

type IconName = ComponentProps<typeof Ionicons>['name'];

const ICONS: Record<ProductCategory, IconName> = {
  lip: 'color-palette-outline',
  cheek: 'flower-outline',
  eye: 'eye-outline',
  base: 'water-outline',
  skincare: 'flask-outline',
  suncare: 'sunny-outline',
};

interface Props {
  uri: string | undefined;
  category?: ProductCategory;
  style?: StyleProp<ImageStyle>;
  recyclingKey?: string;
  /** Hide the "no image" caption on small thumbnails. */
  compact?: boolean;
}

/** Product photo, or a neutral category placeholder. Never substitutes another product's image. */
export function ProductImage({ uri, category, style, recyclingKey, compact }: Props) {
  const { t } = useI18n();
  const [failedUri, setFailedUri] = useState<string | null>(null);

  if (!uri || failedUri === uri) {
    return (
      <View
        style={[styles.placeholder, style as StyleProp<ViewStyle>]}
        accessible
        accessibilityRole="image"
        accessibilityLabel={t('image.unavailable')}>
        <Ionicons name={category ? ICONS[category] : 'image-outline'} size={compact ? 20 : 32} color={theme.colors.inkFaint} />
        {compact ? null : <Text style={styles.caption}>{t('image.unavailable')}</Text>}
      </View>
    );
  }
  return (
    <Image
      source={{ uri }}
      style={style}
      contentFit="cover"
      transition={150}
      recyclingKey={recyclingKey}
      onError={() => setFailedUri(uri)}
    />
  );
}

const styles = StyleSheet.create({
  placeholder: {
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    backgroundColor: theme.colors.cream,
  },
  caption: { fontSize: 11, color: theme.colors.inkFaint },
});
