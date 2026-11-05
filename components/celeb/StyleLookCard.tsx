import Ionicons from '@expo/vector-icons/Ionicons';
import { Image } from 'expo-image';
import { LinearGradient } from 'expo-linear-gradient';
import { memo, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { theme } from '@/constants/theme';
import type { StyleLook } from '@/types';

const PALETTES: Record<string, readonly [string, string]> = {
  '컬러·톤 스타일': ['#B77881', '#69434F'],
  '콘셉트·분위기': ['#A67889', '#4E354D'],
  '시즌·데일리': ['#C29280', '#785049'],
  '보정·맞춤': ['#A8877F', '#65474B'],
  '데일리·활용': ['#B89080', '#755149'],
  '베이스·피부 표현': ['#C5A08E', '#826154'],
  '아이 메이크업': ['#A3889A', '#584359'],
};

export function StyleLookArtwork({ group, videoId, dim = true }: { group: string; videoId?: string; dim?: boolean }) {
  const [failedVideoId, setFailedVideoId] = useState<string | null>(null);
  const imageFailed = !!videoId && failedVideoId === videoId;
  const thumbnail = videoId && /^[A-Za-z0-9_-]{11}$/.test(videoId)
    ? `https://i.ytimg.com/vi/${videoId}/hqdefault.jpg` : null;
  return (
    <View pointerEvents="none" style={StyleSheet.absoluteFill}>
      <LinearGradient colors={PALETTES[group] ?? ['#B77881', '#69434F']} style={StyleSheet.absoluteFill} />
      <View style={styles.circleLarge} />
      <View style={styles.circleSmall} />
      <View style={styles.line} />
      {thumbnail && !imageFailed ? <Image source={{ uri: thumbnail }} style={StyleSheet.absoluteFill} contentFit="cover" transition={150} onError={() => setFailedVideoId(videoId ?? null)} /> : null}
      {thumbnail && !imageFailed && dim ? <LinearGradient colors={['rgba(20,10,14,0.35)', 'rgba(20,10,14,0.78)']} style={StyleSheet.absoluteFill} /> : null}
    </View>
  );
}

interface Props {
  look: StyleLook;
  groupLabel: string;
  productLabel: string;
  onPress: () => void;
  width?: number;
}

export const StyleLookCard = memo(function StyleLookCard({ look, groupLabel, productLabel, onPress, width }: Props) {
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={`${look.title}, ${groupLabel}, ${productLabel}`} onPress={onPress}
      style={({ pressed }) => [styles.card, width !== undefined && { width }, pressed && styles.pressed]}>
      <StyleLookArtwork group={look.group} videoId={look.id} />
      <View style={styles.top}><Text style={styles.topText}>{groupLabel}</Text><Ionicons name="arrow-forward" size={16} color={theme.colors.white} /></View>
      <View style={styles.copy}>
        <Text style={styles.tag} numberOfLines={1}>{look.tag}</Text>
        <Text style={styles.title} numberOfLines={3}>{look.title}</Text>
        <Text style={styles.meta}>{productLabel}</Text>
      </View>
    </Pressable>
  );
});

const styles = StyleSheet.create({
  card: { minHeight: 205, borderRadius: 20, overflow: 'hidden', justifyContent: 'space-between', backgroundColor: '#76505C' },
  circleLarge: { position: 'absolute', width: 180, height: 180, borderRadius: 90, backgroundColor: 'rgba(255,255,255,0.10)', right: -42, top: -55 },
  circleSmall: { position: 'absolute', width: 108, height: 108, borderRadius: 54, borderWidth: 1, borderColor: 'rgba(255,255,255,0.23)', right: 12, top: 32 },
  line: { position: 'absolute', height: 1, width: '65%', backgroundColor: 'rgba(255,255,255,0.22)', right: 0, top: '48%', transform: [{ rotate: '-35deg' }] },
  top: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 6, padding: 14 },
  topText: { color: 'rgba(255,255,255,0.94)', fontSize: 11, fontWeight: '700', flexShrink: 1 },
  copy: { padding: 14, paddingTop: 8 },
  tag: { color: 'rgba(255,255,255,0.83)', fontSize: 11, fontWeight: '600', marginBottom: 5 },
  title: { color: theme.colors.white, fontSize: 17, lineHeight: 23, fontWeight: '800' },
  meta: { color: 'rgba(255,255,255,0.85)', fontSize: 12, marginTop: 8 },
  pressed: { opacity: 0.85 },
});
