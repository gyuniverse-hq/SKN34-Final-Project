import Ionicons from '@expo/vector-icons/Ionicons';
import { Image } from 'expo-image';
import { LinearGradient } from 'expo-linear-gradient';
import { useIsFocused } from 'expo-router';
import { useCallback, useEffect, useMemo, useRef, useState, type ComponentRef } from 'react';
import { Animated, AppState, Easing, Platform, Pressable, ScrollView, StyleSheet, Text, View, type StyleProp, type ViewStyle } from 'react-native';
import { useReducedMotion } from 'react-native-reanimated';
import { InlineState } from '@/components/ui/InlineState';
import { CelebrityPortrait } from './CelebrityAvatar';
import { CELEBRITIES, CELEBRITY_BACKGROUNDS, type CelebrityId } from '@/constants/celebrities';
import { homeLayout, homeType } from '@/constants/homeLayout';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';
import { styleLookGroupLabel } from '@/lib/styleLookGroups';
import type { StyleLook } from '@/types';

type CollectionTab = 'celebrity' | 'style';
const SLIDE_INTERVAL_MS = 5000;
const SLIDE_DURATION_MS = 480;
// Horizontal Bézier handles span 30% from the start and 60% back from the end.
const slideEasing = Easing.bezier(0.30, 0, 0.40, 1);
const webScrollDuringMotion: ViewStyle & { scrollSnapType: 'none' } = { scrollSnapType: 'none' };
const celebrities = [...CELEBRITIES.filter(c => c.id === 'wonyoung'), ...CELEBRITIES.filter(c => c.id !== 'wonyoung')];
const raisedPortraits = new Set<CelebrityId>(['sullyoon', 'winter', 'jennie']);

interface BannerArt { image: number; background: string }

const homeLookArt: Partial<Record<string, BannerArt>> = {
  '1qj6SactPVM': { image: require('@/assets/images/home/styles/neutral-vanilla.webp'), background: '#F5E3D8' },
  'EiYeC-hlMNQ': { image: require('@/assets/images/home/styles/cool-mauve.webp'), background: '#D7CCDB' },
  '_yyvVZ55LuI': { image: require('@/assets/images/home/styles/school-makeup.webp'), background: '#F8D9CF' },
  '325aSOYwqyk': { image: require('@/assets/images/home/styles/feature-definition.webp'), background: '#E3C6C1' },
};

interface Slide {
  id: string;
  title: string;
  group: string;
  background: string;
  portrait?: CelebrityId;
  art?: BannerArt;
  onPress: () => void;
}

interface Props {
  pageWidth: number;
  looks?: StyleLook[];
  looksLoading: boolean;
  looksError: boolean;
  onRetry: () => void;
  onViewAll: (tab: CollectionTab) => void;
  onPressCelebrity: (id: CelebrityId) => void;
  onPressStyle: (look: StyleLook) => void;
}

export function KStyleCollection({ pageWidth, looks, looksLoading, looksError, onRetry, onViewAll, onPressCelebrity, onPressStyle }: Props) {
  const { t } = useI18n();
  const [tab, setTab] = useState<CollectionTab>('celebrity');
  const isCelebrity = tab === 'celebrity';
  const featuredLooks = useMemo(() => {
    const available = looks ?? [];
    const byGroup = new Map<string, StyleLook>();
    for (const id of Object.keys(homeLookArt)) {
      const look = available.find(item => item.id === id);
      if (look) byGroup.set(look.group, look);
    }
    for (const look of available) {
      if (byGroup.size >= 4) break;
      if (!byGroup.has(look.group)) byGroup.set(look.group, look);
    }
    return [...byGroup.values()];
  }, [looks]);
  const slides: Slide[] = isCelebrity
    ? celebrities.map(c => ({ id: c.id, title: t(c.nameKey), group: c.group, background: CELEBRITY_BACKGROUNDS[c.id], portrait: c.id, onPress: () => onPressCelebrity(c.id) }))
    : featuredLooks.map(look => ({ id: look.id, title: look.title, group: styleLookGroupLabel(look.group, t), background: homeLookArt[look.id]?.background ?? theme.colors.cream, art: homeLookArt[look.id], onPress: () => onPressStyle(look) }));
  const unavailable = !isCelebrity && (looksLoading || looksError || !slides.length);
  return (
    <View style={styles.collection}>
      {unavailable ? <View style={styles.state}>
        <InlineState status={looksLoading ? 'loading' : looksError ? 'error' : 'empty'} message={looksError ? undefined : t('looks.empty')} onRetry={onRetry} />
      </View> : <BannerPages key={`${tab}-${pageWidth}-${slides.map(s => s.id).join(',')}`} slides={slides} width={pageWidth} actionLabel={t('home.viewLook')} />}
      <View pointerEvents="box-none" style={styles.toolbar}>
        <View accessibilityRole="tablist" style={styles.tabs}>
          {(['celebrity', 'style'] as const).map(item => (
            <Pressable key={item} accessibilityRole="tab" aria-selected={tab === item}
              onPress={() => setTab(item)} style={[styles.tab, tab === item && styles.selectedTab]}>
              <Text style={[styles.tabText, tab === item && styles.selectedText]}>{t(item === 'celebrity' ? 'home.collectionCelebrity' : 'home.collectionStyle')}</Text>
            </Pressable>
          ))}
        </View>
        <Pressable accessibilityRole="button" hitSlop={5} onPress={() => onViewAll(tab)} style={styles.all}>
          <Text style={styles.allText}>{t('home.viewAll')}</Text>
          <Ionicons name="chevron-forward" size={12} color={theme.colors.rose} />
        </Pressable>
      </View>
    </View>
  );
}

function BannerPages({ slides, width, actionLabel }: { slides: Slide[]; width: number; actionLabel: string }) {
  const [page, setPage] = useState(0);
  const scroll = useRef<ComponentRef<typeof ScrollView>>(null);
  const focused = useIsFocused();
  const reduceMotion = useReducedMotion();
  const [foreground, setForeground] = useState(AppState.currentState !== 'background' && AppState.currentState !== 'inactive');
  const [touching, setTouching] = useState(false);
  const [moving, setMoving] = useState(false);
  const offset = useRef(0);
  const frame = useRef<number | null>(null);
  const count = slides.length;
  const stopMoving = useCallback(() => {
    if (frame.current !== null) cancelAnimationFrame(frame.current);
    frame.current = null;
    setMoving(false);
  }, []);
  const goToPage = useCallback((index: number) => {
    stopMoving();
    const from = offset.current;
    const target = index * width;
    if (reduceMotion || Math.abs(target - from) < 1) {
      scroll.current?.scrollTo({ x: target, animated: false });
      return;
    }
    // Native scrollTo(animated: true) does not accept a timing curve.
    setMoving(true);
    const startedAt = performance.now();
    const step = () => {
      const progress = Math.min(1, (performance.now() - startedAt) / SLIDE_DURATION_MS);
      if (progress === 1) {
        offset.current = (index % count) * width;
        scroll.current?.scrollTo({ x: offset.current, animated: false });
        setPage(index % count);
        stopMoving();
      } else {
        scroll.current?.scrollTo({ x: from + (target - from) * slideEasing(progress), animated: false });
        frame.current = requestAnimationFrame(step);
      }
    };
    frame.current = requestAnimationFrame(step);
  }, [count, reduceMotion, stopMoving, width]);
  useEffect(() => {
    if (focused && foreground && !reduceMotion) return stopMoving;
  }, [focused, foreground, reduceMotion, stopMoving]);
  useEffect(() => {
    const sub = AppState.addEventListener('change', state => setForeground(state === 'active'));
    return () => sub.remove();
  }, []);
  useEffect(() => {
    if (!focused || !foreground || touching || reduceMotion || count < 2) return;
    const timer = setInterval(() => goToPage(Math.round(offset.current / width) % count + 1), SLIDE_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [focused, foreground, touching, reduceMotion, count, goToPage, width]);

  // A trailing copy lets the final slide advance one page, then return to the identical first page.
  const pages = count > 1 ? [...slides, slides[0]] : slides;
  const bannerHeight = (width - 20) / 1.97;
  const height = bannerHeight + 46;
  return (
    <View style={{ height }}>
      <ScrollView ref={scroll} horizontal pagingEnabled={Platform.OS === 'web' || !moving} showsHorizontalScrollIndicator={false}
        style={Platform.OS === 'web' && moving && webScrollDuringMotion}
        onTouchStart={() => { stopMoving(); setTouching(true); }} onTouchEnd={() => setTouching(false)} onTouchCancel={() => setTouching(false)}
        onScroll={event => {
          const x = event.nativeEvent.contentOffset.x;
          offset.current = x;
          const index = Math.max(0, Math.min(pages.length - 1, Math.round(x / width)));
          setPage(index % count);
          if (frame.current === null && count > 1 && x >= count * width - 1) {
            offset.current = 0;
            scroll.current?.scrollTo({ x: 0, animated: false });
          }
        }}
        scrollEventThrottle={32}>
        {pages.map((slide, index) => (
          <View key={index === count ? 'loop-start' : slide.id} aria-hidden={index === count} style={[styles.page, { width, height }]}>
            <Pressable accessibilityRole="button" accessibilityLabel={`${slide.title}, ${actionLabel}`} focusable={index !== count}
              onPress={slide.onPress} style={styles.banner}>
              <View style={[styles.plate, { height: bannerHeight, backgroundColor: slide.background }]}>
                {slide.art && <>
                  <BannerPhoto active={page === index % count} reduceMotion={reduceMotion} style={styles.lookPhoto}>
                    <Image source={slide.art.image} style={StyleSheet.absoluteFill} contentFit="cover" />
                  </BannerPhoto>
                  <LinearGradient colors={[slide.art.background, slide.art.background + '00']}
                    start={{ x: 0, y: 0.5 }} end={{ x: 1, y: 0.5 }} style={styles.photoEdge} />
                </>}
              </View>
              {slide.portrait && <BannerPhoto active={page === index % count} reduceMotion={reduceMotion}
                style={[styles.portrait, raisedPortraits.has(slide.portrait) && styles.raisedPortrait]}>
                <CelebrityPortrait id={slide.portrait} />
              </BannerPhoto>}
              <View style={[styles.copy, { height: bannerHeight }, !slide.portrait && styles.lookCopy]}>
                {!!slide.group && <Text numberOfLines={1} style={slide.portrait ? styles.group : styles.lookGroup}>{slide.group}</Text>}
                <Text numberOfLines={2} adjustsFontSizeToFit style={slide.portrait ? styles.name : styles.lookTitle}>
                  {slide.art ? slide.title.replace(/ 메이크업$/, '\n메이크업') : slide.title}
                </Text>
                <View style={styles.cta}><Text style={styles.ctaText}>{actionLabel}</Text><Ionicons name="arrow-forward" size={15} color={theme.colors.white} /></View>
              </View>
            </Pressable>
          </View>
        ))}
      </ScrollView>
      {slides.length > 1 && <View style={styles.dots}>
        {slides.map((slide, index) => (
          <Pressable key={slide.id} accessibilityRole="button" accessibilityLabel={slide.title} accessibilityState={{ selected: index === page }}
            onPressIn={() => setTouching(true)} onPressOut={() => setTouching(false)} onPress={() => goToPage(index)}
            style={styles.dotHit}><View style={[styles.dot, index === page && styles.currentDot]} /></Pressable>
        ))}
      </View>}
    </View>
  );
}

function BannerPhoto({ children, style, active, reduceMotion }: {
  children: React.ReactNode; style: StyleProp<ViewStyle>; active: boolean; reduceMotion: boolean;
}) {
  const [entrance] = useState(() => new Animated.Value(reduceMotion ? 1 : 0));
  useEffect(() => {
    if (reduceMotion) {
      entrance.setValue(1);
      return;
    }
    const animation = Animated.timing(entrance, {
      toValue: active ? 1 : 0, duration: active ? SLIDE_DURATION_MS : 220,
      easing: slideEasing, useNativeDriver: Platform.OS !== 'web',
    });
    animation.start();
    return () => animation.stop();
  }, [active, reduceMotion, entrance]);
  return (
    <Animated.View pointerEvents="none" style={[style, {
      opacity: entrance.interpolate({ inputRange: [0, 1], outputRange: [0.25, 1] }),
      transform: [{ scale: entrance.interpolate({ inputRange: [0, 1], outputRange: [0.96, 1] }) }],
    }]}>
      {children}
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  collection: { backgroundColor: homeLayout.background },
  state: { marginTop: 48, marginHorizontal: homeLayout.gutter },
  toolbar: { position: 'absolute', top: 2, left: 17, right: 15, height: 39, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  tabs: { flexDirection: 'row', alignItems: 'center', gap: 19 },
  tab: { minHeight: 35, justifyContent: 'center', borderBottomWidth: 2, borderBottomColor: 'transparent' },
  selectedTab: { borderBottomColor: theme.colors.rose },
  tabText: { ...homeType(15), fontWeight: '500', color: theme.colors.inkMuted },
  selectedText: { color: theme.colors.roseDark, fontWeight: '600' },
  all: { flexDirection: 'row', alignItems: 'center', gap: 2, minHeight: 34 },
  allText: { ...homeType(12), color: theme.colors.rose },
  page: { paddingHorizontal: 10 },
  banner: { flex: 1, borderRadius: 16, overflow: 'hidden' },
  plate: { position: 'absolute', bottom: 0, width: '100%', borderRadius: 16, overflow: 'hidden' },
  portrait: { position: 'absolute', right: 0, bottom: 0, width: '58%', aspectRatio: 1 },
  raisedPortrait: { width: '62.6%', right: '-2.3%' },
  copy: { position: 'absolute', bottom: 0, left: '6%', width: '45%', justifyContent: 'center', alignItems: 'flex-start', paddingBottom: 8 },
  lookPhoto: { position: 'absolute', right: 0, width: '60%', height: '100%' },
  photoEdge: { position: 'absolute', left: '39.5%', width: '9%', height: '100%' },
  lookCopy: { width: '46%' },
  group: { ...homeType(15), fontFamily: theme.fontFamily.regular, color: theme.colors.roseDark },
  lookGroup: { ...homeType(13), fontWeight: '500', color: theme.colors.roseDark, marginBottom: 3 },
  name: {
    ...homeType(32),
    fontFamily: Platform.select({ android: 'sans-serif', ios: 'System', default: 'system-ui, sans-serif' }),
    fontWeight: '700',
    color: theme.colors.roseDark,
  },
  lookTitle: { ...homeType(22), lineHeight: 28, fontFamily: homeLayout.displayFont, color: theme.colors.roseDark },
  cta: { marginTop: 10, minHeight: 30, borderRadius: 18, paddingHorizontal: 14, flexDirection: 'row',
    alignItems: 'center', gap: 7, backgroundColor: theme.colors.roseDark },
  ctaText: { ...homeType(13), fontWeight: '500', color: theme.colors.white },
  dots: { position: 'absolute', bottom: 3, left: 26, flexDirection: 'row' },
  dotHit: { paddingHorizontal: 3, height: 22, justifyContent: 'center' },
  dot: { width: 5, height: 5, borderRadius: 3, backgroundColor: '#FFF4EF' },
  currentDot: { backgroundColor: theme.colors.roseDark },
});
