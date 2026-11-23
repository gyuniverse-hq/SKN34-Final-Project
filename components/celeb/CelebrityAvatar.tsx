import { Image } from 'expo-image';
import { useState } from 'react';
import { StyleSheet, Text, View, type ImageStyle } from 'react-native';
import { CELEBRITY_BACKGROUNDS, CELEBRITY_PORTRAITS, type CelebrityId } from '@/constants/celebrities';
import { theme } from '@/constants/theme';

export function CelebrityAvatar({ id, name }: { id: CelebrityId; name: string }) {
  const [failedId, setFailedId] = useState<CelebrityId>();
  return (
    <View style={[styles.portrait, { backgroundColor: CELEBRITY_BACKGROUNDS[id] }]}>
      {failedId === id ? <Text style={styles.initial}>{name.slice(0, 1)}</Text> : (
        <CelebrityPortrait id={id} onError={() => setFailedId(id)} />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  portrait: { width: '100%', aspectRatio: 1, borderRadius: 12, overflow: 'hidden',
    alignItems: 'center', justifyContent: 'center' },
  initial: { color: theme.colors.roseDark, fontSize: 24 },
});

// Place the eyes near the horizontal center, 47% down a square frame.
// Each cutout keeps its original aspect ratio, including the taller source photos.
const framing: Record<CelebrityId, ImageStyle> = {
  haerin:   { width: '102%', left: '0%',   top: '-1%', aspectRatio: 1 },
  jennie:   { width: '100%', left: '0%',   top: '12%', aspectRatio: 1 },
  karina:   { width: '114%', left: '-4%',  top: '7%',  aspectRatio: 480 / 640 },
  sullyoon: { width: '105%', left: '-2%',  top: '10%', aspectRatio: 1 },
  winter:   { width: '109%', left: '-1%',  top: '13%', aspectRatio: 1 },
  wony:     { width: '132%', left: '-13%', top: '1%',  aspectRatio: 486 / 720 },
  wonyoung: { width: '109%', left: '-7%',  top: '4%',  aspectRatio: 640 / 677 },
};

export function CelebrityPortrait({ id, onError }: { id: CelebrityId; onError?: () => void }) {
  return <Image source={CELEBRITY_PORTRAITS[id]} style={[{ position: 'absolute' }, framing[id]]}
    contentFit="contain" onError={onError} />;
}
