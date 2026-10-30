import Ionicons from '@expo/vector-icons/Ionicons';
import { memo } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { InlineState } from '@/components/ui/InlineState';
import { CelebrityCard } from './CelebrityCard';
import { StyleLookCard } from './StyleLookCard';
import type { Celebrity } from '@/constants/celebrities';
import { theme } from '@/constants/theme';
import type { StyleLook } from '@/types';

export type KStyleCollectionTab = 'celebrity' | 'style';

interface Props {
  activeTab: KStyleCollectionTab;
  celebrities: { celebrity: Celebrity; name: string }[];
  looks: StyleLook[] | undefined;
  looksLoading: boolean;
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
  onPressCelebrity: (celebrity: Celebrity) => void;
  onPressStyle: (look: StyleLook) => void;
  groupLabel: (group: string) => string;
  productLabel: (count: number) => string;
}

/** Home's high-priority, image-first entry point for K-celebrity and K-style looks. */
export const KStyleCollection = memo(function KStyleCollection({
  activeTab,
  celebrities,
  looks,
  looksLoading,
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
  onPressCelebrity,
  onPressStyle,
  groupLabel,
  productLabel,
}: Props) {
  const isCelebrity = activeTab === 'celebrity';
  const loading = !isCelebrity && looksLoading;
  const hasError = !isCelebrity && looksError;
  const isEmpty = isCelebrity ? celebrities.length === 0 : !looks?.length;
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
      ) : isEmpty ? (
        <InlineState status="empty" message={emptyMessage} />
      ) : (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.rail}>
          {isCelebrity
            ? celebrities.map(({ celebrity, name }) => (
                <CelebrityCard key={celebrity.id} celebrity={celebrity} name={name} label={activeLabel} lookbook
                  onPress={() => onPressCelebrity(celebrity)} />
              ))
            : looks?.map((look) => (
                <StyleLookCard
                  key={look.id}
                  look={look}
                  groupLabel={groupLabel(look.group)}
                  productLabel={productLabel(look.products.length)}
                  width={200}
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
  pressed: { opacity: 0.9 },
});
