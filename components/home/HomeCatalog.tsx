import Ionicons from '@expo/vector-icons/Ionicons';
import { Image } from 'expo-image';
import { LinearGradient } from 'expo-linear-gradient';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { ProductImage } from '@/components/ui/ProductImage';
import { homeHeading, homeLayout, homeType } from '@/constants/homeLayout';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';
import { PRODUCT_CATEGORIES } from '@/lib/routes';
import type { Product, ProductCategory } from '@/types';

const categoryImages: Record<ProductCategory, number> = {
  lip: require('@/assets/images/home/categories/lip.webp'),
  cheek: require('@/assets/images/home/categories/cheek.webp'),
  eye: require('@/assets/images/home/categories/eye.webp'),
  base: require('@/assets/images/home/categories/base.webp'),
  skincare: require('@/assets/images/home/categories/skincare.webp'),
  suncare: require('@/assets/images/home/categories/suncare.webp'),
  tool: require('@/assets/images/home/categories/tool.webp'),
};

// Category still lifes illustrate the unpublished state; product cards use the catalog photo.
const previewArt = {
  makeup: [
    require('@/assets/images/home/editorial/lipstick.webp'), require('@/assets/images/home/editorial/cushion.webp'),
    require('@/assets/images/home/editorial/palette.webp'),
  ],
  skincare: [
    require('@/assets/images/home/editorial/serum.webp'), require('@/assets/images/home/editorial/toner.webp'),
    require('@/assets/images/home/editorial/cream.webp'),
  ],
  new: [
    require('@/assets/images/home/editorial/tint.webp'), require('@/assets/images/home/editorial/ampoule.webp'),
    require('@/assets/images/home/editorial/oil.webp'),
  ],
} as const;

export function HomeCategories({ onPress }: { onPress: (category: ProductCategory) => void }) {
  const { t } = useI18n();
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.categories}>
      {PRODUCT_CATEGORIES.map(category => (
        <Pressable key={category} accessibilityRole="button" onPress={() => onPress(category)} style={styles.category}>
          <View style={styles.categoryTile}>
            <Image source={categoryImages[category]} style={styles.categoryPhoto} contentFit="contain" />
          </View>
          <Text style={styles.categoryText}>{t(`shop.cat.${category}`)}</Text>
        </Pressable>
      ))}
    </ScrollView>
  );
}

interface Props {
  title: string;
  products: Product[];
  emptyMessage: string;
  pageWidth: number;
  featured?: boolean;
  preview?: keyof typeof previewArt;
  onViewAll?: () => void;
  onPress: (product: Product) => void;
}

function FeaturedArtwork({ product, message }: { product?: Product; message?: string }) {
  return (
    <>
      {product
        ? <ProductImage uri={product.imageUrl} category={product.category} recyclingKey={product.id} style={styles.featureImage} />
        : <Image source={require('@/assets/images/home/editorial/blush.webp')} contentFit="cover" style={styles.featureImage} />}
      <LinearGradient pointerEvents="none" colors={['#FBE2D6', '#FBE2D6', 'rgba(251,226,214,0)']} locations={[0, 0.43, 0.72]}
        start={{ x: 0, y: 0 }} end={{ x: 1, y: 0 }} style={StyleSheet.absoluteFill} />
      <View style={styles.featureCopy}>
        {product ? <>
          <Text numberOfLines={2} style={styles.featureName}>{product.name}</Text>
          <Text numberOfLines={2} style={styles.brand}>{product.brand}</Text>
        </> : <Text style={styles.featureStatus}>{message}</Text>}
      </View>
    </>
  );
}

function EmptyShelf({ message, preview, featured, width }: Pick<Props, 'featured' | 'preview'> & { message: string; width: number }) {
  if (featured) {
    return (
      <View accessible accessibilityLabel={message} style={[styles.feature, styles.emptyFeature, { width }]}>
        <FeaturedArtwork message={message} />
      </View>
    );
  }
  if (!preview) return <Text style={styles.empty}>{message}</Text>;
  return (
    <View accessible accessibilityLabel={message} style={styles.preview}>
      <View style={styles.previewImages} importantForAccessibility="no-hide-descendants" aria-hidden>
        {previewArt[preview].map((source, index) => (
          <Image key={index} source={source} contentFit="cover" style={[styles.productPhoto, { width }]} />
        ))}
      </View>
      <View pointerEvents="none" style={styles.previewStatus}><Text style={styles.statusText}>{message}</Text></View>
    </View>
  );
}

export function HomeProductSection({ title, products, emptyMessage, pageWidth, featured, preview, onViewAll, onPress }: Props) {
  const { t } = useI18n();
  const innerWidth = pageWidth - 2 * homeLayout.gutter;
  const width = featured ? innerWidth - 18 : (innerWidth - 2 * homeLayout.productGap) / 3;
  return (
    <View style={styles.section}>
      <View style={styles.headingRow}>
        <Text accessibilityRole="header" style={styles.heading}>{title}</Text>
        {onViewAll && (
          <Pressable accessibilityRole="button" accessibilityLabel={`${title}, ${t('home.viewAll')}`}
            onPress={onViewAll} hitSlop={6} style={styles.more}>
            <Text style={styles.moreText}>{t('home.viewAll')}</Text>
            <Ionicons name="chevron-forward" size={13} color={theme.colors.rose} />
          </Pressable>
        )}
      </View>
      {products.length === 0 ? (
        <EmptyShelf message={emptyMessage} preview={preview} featured={featured} width={width} />
      ) : (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.rail}
          snapToInterval={featured ? width + homeLayout.productGap : undefined} decelerationRate={featured ? 'fast' : 'normal'}>
          {products.slice(0, 8).map(product => (
            <Pressable key={product.id} accessibilityRole="button" accessibilityLabel={`${product.brand} ${product.name}`}
              onPress={() => onPress(product)} style={[{ width }, featured && styles.feature]}>
              {featured ? (
                <FeaturedArtwork product={product} />
              ) : (
                <>
                  <ProductImage uri={product.imageUrl} category={product.category} recyclingKey={product.id} compact style={styles.productPhoto} />
                  <Text numberOfLines={2} style={styles.productName}>{product.name}</Text>
                </>
              )}
            </Pressable>
          ))}
        </ScrollView>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  categories: { paddingHorizontal: homeLayout.gutter, paddingTop: 10, paddingBottom: 15, gap: 8 },
  category: { minWidth: homeLayout.categorySize, alignItems: 'center' },
  categoryTile: { width: homeLayout.categorySize, height: homeLayout.categorySize, borderRadius: 8,
    backgroundColor: '#F3E7E3', alignItems: 'center', justifyContent: 'center' },
  categoryPhoto: { width: 38, height: 38 },
  categoryText: { ...homeType(12), lineHeight: 17, marginTop: 4, color: theme.colors.ink },
  section: { marginBottom: 23 },
  headingRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginHorizontal: homeLayout.gutter, marginBottom: 10 },
  heading: { ...homeHeading, flexShrink: 1 },
  more: { flexDirection: 'row', alignItems: 'center', gap: 3, minHeight: 26 },
  moreText: { ...homeType(12), color: theme.colors.rose },
  rail: { paddingHorizontal: homeLayout.gutter, gap: homeLayout.productGap, alignItems: 'flex-start' },
  productPhoto: { width: '100%', aspectRatio: 1, borderRadius: 9, backgroundColor: theme.colors.cream },
  productName: { ...homeType(13), lineHeight: 18, marginTop: 5, color: theme.colors.ink, textAlign: 'center' },
  feature: { aspectRatio: 342 / 173, borderRadius: 12, overflow: 'hidden', backgroundColor: '#FBE2D6', justifyContent: 'center' },
  featureImage: { position: 'absolute', right: 0, width: '60%', height: '100%' },
  featureCopy: { width: '53%', paddingLeft: 18 },
  featureName: { ...homeType(22), lineHeight: 29, fontFamily: homeLayout.displayFont, color: theme.colors.roseDark },
  brand: { ...homeType(12), marginTop: 8, color: theme.colors.inkMuted },
  emptyFeature: { marginLeft: homeLayout.gutter },
  featureStatus: { ...homeType(16), lineHeight: 23, fontWeight: '600', color: theme.colors.roseDark },
  preview: { marginHorizontal: homeLayout.gutter, justifyContent: 'center', alignItems: 'center' },
  previewImages: { flexDirection: 'row', gap: homeLayout.productGap, opacity: 0.60 },
  previewStatus: { position: 'absolute', maxWidth: '90%', paddingHorizontal: 14, paddingVertical: 6,
    borderRadius: 20, backgroundColor: homeLayout.background },
  statusText: { ...homeType(12), lineHeight: 18, textAlign: 'center', color: theme.colors.inkMuted },
  empty: { ...homeType(13), marginHorizontal: homeLayout.gutter, paddingVertical: 16, color: theme.colors.inkMuted },
});
