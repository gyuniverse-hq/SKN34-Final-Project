import Ionicons from '@expo/vector-icons/Ionicons';
import { Image } from 'expo-image';
import { LinearGradient } from 'expo-linear-gradient';
import { memo, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import type { Celebrity } from '@/constants/celebrities';
import { theme } from '@/constants/theme';

export const CelebrityCard = memo(function CelebrityCard({ celebrity, name, label, onPress, wide = false, lookbook = false }: {
  celebrity: Celebrity; name: string; label: string; onPress: () => void; wide?: boolean; lookbook?: boolean;
}) {
  const [imageFailed, setImageFailed] = useState(false);
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={`${name}, ${label}`} onPress={onPress}
      style={({ pressed }) => [styles.card, wide && styles.wide, lookbook && styles.lookbook, pressed && styles.pressed]}>
      {!imageFailed && <Image source={celebrity.image} style={StyleSheet.absoluteFill} contentFit="cover" transition={150} onError={() => setImageFailed(true)} />}
      <LinearGradient colors={['rgba(32,16,24,0.05)', 'rgba(20,10,14,0.9)']} locations={[0.28, 1]} style={StyleSheet.absoluteFill} />
      {lookbook ? <>
        <View style={styles.lookbookTop}><Text style={styles.lookbookLabel}>{label}</Text><Ionicons name="arrow-forward" size={16} color={theme.colors.white} /></View>
        <View style={styles.lookbookCopy}>{celebrity.group ? <Text style={styles.lookbookGroup}>{celebrity.group}</Text> : null}<Text style={styles.lookbookTitle}>{name}</Text></View>
      </> : <>
        <View style={styles.copy}>
          <Text style={styles.eyebrow}>{label}{celebrity.group ? ` · ${celebrity.group}` : ''}</Text>
          <Text style={styles.title}>{name}</Text>
        </View>
        <View style={styles.arrow} pointerEvents="none"><Ionicons name="chevron-forward" size={18} color={theme.colors.white} /></View>
      </>}
    </Pressable>
  );
});

const styles = StyleSheet.create({
  card: { backgroundColor: '#725662', borderRadius: theme.radius.lg, height: 292, overflow: 'hidden', width: 248 },
  wide: { width: '100%', height: 220 },
  lookbook: { width: 200, height: 205, borderRadius: 20, justifyContent: 'space-between' },
  lookbookTop: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 6, padding: 14 },
  lookbookLabel: { color: 'rgba(255,255,255,0.94)', fontSize: 11, fontWeight: '700', flexShrink: 1 },
  lookbookCopy: { padding: 14, paddingTop: 8 },
  lookbookGroup: { color: 'rgba(255,255,255,0.83)', fontSize: 11, fontWeight: '600', marginBottom: 5 },
  lookbookTitle: { color: theme.colors.white, fontSize: 17, lineHeight: 23, fontWeight: '800' },
  copy: { bottom: 18, left: 18, position: 'absolute', right: 60 },
  eyebrow: { color: 'rgba(255,255,255,0.95)', fontSize: 11, fontWeight: '800', letterSpacing: 0.9 },
  title: { color: theme.colors.white, fontSize: theme.font.h2, fontWeight: '900', marginTop: 6 },
  arrow: { alignItems: 'center', backgroundColor: 'rgba(255,255,255,0.18)', borderRadius: 22, bottom: 18, height: 44, justifyContent: 'center', position: 'absolute', right: 16, width: 44 },
  pressed: { opacity: 0.9 },
});
