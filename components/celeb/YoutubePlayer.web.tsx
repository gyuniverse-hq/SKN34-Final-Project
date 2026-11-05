import { useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { theme } from '@/constants/theme';

export function YoutubePlayer({ videoId, startSeconds = 0, title }: { videoId: string; startSeconds?: number; title: string }) {
  const [focused, setFocused] = useState(false);
  useFocusEffect(useCallback(() => { setFocused(true); return () => setFocused(false); }, []));
  const validId = /^[A-Za-z0-9_-]{11}$/.test(videoId);
  const start = Number.isFinite(startSeconds) && startSeconds > 0 ? Math.floor(startSeconds) : 0;
  return <View style={styles.container}>{focused && validId ? <iframe
    title={title}
    src={`https://www.youtube.com/embed/${videoId}?playsinline=1&start=${start}`}
    allow="encrypted-media; picture-in-picture; fullscreen"
    allowFullScreen
    style={{ width: '100%', height: '100%', border: 0 }}
  /> : null}</View>;
}

const styles = StyleSheet.create({
  container: { width: '100%', aspectRatio: 16 / 9, minHeight: 200, borderRadius: 20, overflow: 'hidden', backgroundColor: theme.colors.black },
});
