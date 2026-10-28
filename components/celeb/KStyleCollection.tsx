import Ionicons from '@expo/vector-icons/Ionicons';
import { Image } from 'expo-image';
import { LinearGradient } from 'expo-linear-gradient';
import { memo } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { InlineState } from '@/components/ui/InlineState';
import { theme } from '@/constants/theme';
import type { CelebLook, IdolLook } from '@/types';

export type KStyleCollectionTab = 'celebrity' | 'style';

interface Props {
  activeTab: KStyleCollectionTab;
  idolLooks: IdolLook[] | undefined;
  looks: CelebLook[] | undefined;
  idolLoading: boolean;
  looksLoading: boolean;
  idolError: boolean;
  looksError: boolean;
  eyebrow: string;
  title: string;
  celebrityLabel: string;
  styleLabel: string;
  viewAllLabel: string;
  emptyMessage: string;
  onTabChange: (tab: KStyleCollectionTab) => void;
  onViewAll: () => void;
  onRetry: () => void;
  onPressIdol: (look: IdolLook) => void;
  onPressStyle: (look: CelebLook) => void;
}

/** Home's high-priority, image-first entry point for K-celebrity and K-style looks. */
export const KStyleCollection = memo(function KStyleCollection({
  activeTab,
  idolLooks,
  looks,
  idolLoading,
  looksLoading,
  idolError,
  looksError,
  eyebrow,
  title,
  celebrityLabel,
  styleLabel,
  viewAllLabel,
  emptyMessage,
  onTabChange,
  onViewAll,
  onRetry,
  onPressIdol,
  onPressStyle,
}: Props) {
  const isCelebrity = activeTab === 'celebrity';
  const loading = isCelebrity ? idolLoading : looksLoading;
  const hasError = isCelebrity ? idolError : looksError;
  const items = isCelebrity ? idolLooks : looks;
  const activeLabel = isCelebrity ? celebrityLabel : styleLabel;

  return (
    <View style={styles.section}>
      <View style={styles.heading}>
        <View>
          <Text style={styles.eyebrow}>{eyebrow}</Text>
          <Text accessibilityRole="header" style={styles.title}>
            {title}
          </Text>
        </View>
        <Pressable accessibilityRole="button" accessibilityLabel={viewAllLabel} hitSlop={8} onPress={onViewAll} style={styles.allButton}>
          <Text style={styles.allText}>{viewAllLabel}</Text>
          <Ionicons name="chevron-forward" size={16} color={theme.colors.rose} />
        </Pressable>
      </View>

      <View style={styles.tabs} accessibilityRole="tablist">
        <CollectionTab label={celebrityLabel} selected={isCelebrity} onPress={() => onTabChange('celebrity')} />
        <CollectionTab label={styleLabel} selected={!isCelebrity} onPress={() => onTabChange('style')} />
      </View>

      {loading ? (
        <InlineState status="loading" />
      ) : hasError ? (
        <InlineState status="error" onRetry={onRetry} />
      ) : !items?.length ? (
        <InlineState status="empty" message={emptyMessage} />
      ) : (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.rail}>
          {isCelebrity
            ? idolLooks?.map((look) => (
                <CollectionCard
                  key={look.id}
                  eyebrow={activeLabel}
                  title={look.displayName}
                  description={look.styleDescription}
                  imageUri={look.video.thumbnailUrl}
                  onPress={() => onPressIdol(look)}
                />
              ))
            : looks?.map((look) => (
                <CollectionCard
                  key={look.id}
                  eyebrow={activeLabel}
                  title={look.title}
                  description={look.description}
                  imageUri={look.thumbnailUrl}
                  onPress={() => onPressStyle(look)}
                />
              ))}
        </ScrollView>
      )}
    </View>
  );
});

function CollectionTab({ label, selected, onPress }: { label: string; selected: boolean; onPress: () => void }) {
  return (
    <Pressable
      accessibilityRole="tab"
      accessibilityLabel={label}
      accessibilityState={{ selected }}
      hitSlop={4}
      onPress={onPress}
      style={({ pressed }) => [styles.tab, selected && styles.tabSelected, pressed && styles.pressed]}>
      <Text style={[styles.tabText, selected && styles.tabTextSelected]}>{label}</Text>
    </Pressable>
  );
}

function CollectionCard({
  eyebrow,
  title,
  description,
  imageUri,
  onPress,
}: {
  eyebrow: string;
  title: string;
  description: string;
  imageUri: string;
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`${eyebrow}. ${title}. ${description}`}
      onPress={onPress}
      style={({ pressed }) => [styles.card, pressed && styles.pressed]}>
      <Image source={{ uri: imageUri }} style={StyleSheet.absoluteFill} contentFit="cover" transition={150} />
      <LinearGradient colors={['rgba(20,10,14,0.02)', 'rgba(20,10,14,0.86)']} locations={[0.28, 1]} style={StyleSheet.absoluteFill} />
      <View style={styles.cardCopy}>
        <Text style={styles.cardEyebrow} numberOfLines={1}>
          {eyebrow}
        </Text>
        <Text style={styles.cardTitle} numberOfLines={2}>
          {title}
        </Text>
        <Text style={styles.cardDescription} numberOfLines={1}>
          {description}
        </Text>
      </View>
      <View style={styles.cardArrow} pointerEvents="none">
        <Ionicons name="chevron-forward" size={18} color={theme.colors.white} />
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  section: { marginTop: 18 },
  heading: { flexDirection: 'row', alignItems: 'flex-end', justifyContent: 'space-between', gap: 12 },
  eyebrow: { color: theme.colors.accent, fontSize: 11, fontWeight: '800', letterSpacing: 1.3 },
  title: { color: theme.colors.ink, fontSize: 20, fontWeight: '800', letterSpacing: -0.3, marginTop: 4 },
  allButton: { flexDirection: 'row', alignItems: 'center', minHeight: theme.hitTarget, marginRight: -4, paddingHorizontal: 4 },
  allText: { color: theme.colors.rose, fontSize: theme.font.small, fontWeight: '800' },
  tabs: { flexDirection: 'row', gap: 8, marginTop: 12, marginBottom: 14 },
  tab: { backgroundColor: theme.colors.roseSoft, borderRadius: theme.radius.pill, height: 36, justifyContent: 'center', paddingHorizontal: 14 },
  tabSelected: { backgroundColor: theme.colors.rose },
  tabText: { color: theme.colors.roseDark, fontSize: 13, fontWeight: '800' },
  tabTextSelected: { color: theme.colors.white },
  rail: { gap: 12, paddingRight: 8 },
  card: { backgroundColor: theme.colors.surfaceAlt, borderRadius: theme.radius.lg, height: 292, overflow: 'hidden', width: 248 },
  cardCopy: { bottom: 18, left: 18, position: 'absolute', right: 18 },
  cardEyebrow: { color: 'rgba(255,255,255,0.95)', fontSize: 11, fontWeight: '800', letterSpacing: 0.9 },
  cardTitle: { color: theme.colors.white, fontSize: theme.font.h2, fontWeight: '900', letterSpacing: -0.6, marginTop: 6 },
  cardDescription: { color: 'rgba(255,255,255,0.9)', fontSize: theme.font.small, fontWeight: '600', marginTop: 4 },
  cardArrow: { alignItems: 'center', backgroundColor: 'rgba(255,255,255,0.18)', borderRadius: 22, bottom: 18, height: 44, justifyContent: 'center', position: 'absolute', right: 16, width: 44 },
  pressed: { opacity: 0.9 },
});
