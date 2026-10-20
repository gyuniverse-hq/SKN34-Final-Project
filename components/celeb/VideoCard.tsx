import Ionicons from '@expo/vector-icons/Ionicons';
import { Image } from 'expo-image';
import * as WebBrowser from 'expo-web-browser';
import { memo } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { theme } from '@/constants/theme';
import type { YoutubeVideo } from '@/types';

export function openYoutubeVideo(videoId: string) {
  return WebBrowser.openBrowserAsync(`https://www.youtube.com/watch?v=${encodeURIComponent(videoId)}`);
}

export const VideoCard = memo(function VideoCard({ video }: { video: YoutubeVideo }) {
  return (
    <Pressable
      onPress={() => openYoutubeVideo(video.videoId)}
      accessibilityRole="link"
      accessibilityLabel={`${video.title}, ${video.channelTitle}`}
      style={({ pressed }) => [styles.row, pressed && { opacity: 0.85 }]}>
      <View>
        <Image source={{ uri: video.thumbnailUrl }} style={styles.thumb} contentFit="cover" transition={120} />
        <View style={styles.play}>
          <Ionicons name="play" size={14} color={theme.colors.white} />
        </View>
      </View>
      <View style={styles.body}>
        <Text style={styles.title} numberOfLines={2}>
          {video.title}
        </Text>
        <Text style={styles.channel} numberOfLines={1}>
          {video.channelTitle}
        </Text>
      </View>
    </Pressable>
  );
});

const styles = StyleSheet.create({
  row: { flexDirection: 'row', gap: 12, paddingVertical: 8 },
  thumb: { width: 140, height: 79, borderRadius: theme.radius.sm, backgroundColor: theme.colors.surfaceAlt },
  play: {
    position: 'absolute',
    right: 6,
    bottom: 6,
    backgroundColor: 'rgba(0,0,0,0.65)',
    borderRadius: 10,
    paddingHorizontal: 6,
    paddingVertical: 3,
  },
  body: { flex: 1, gap: 4 },
  title: { fontSize: theme.font.small, fontWeight: '600', color: theme.colors.ink, lineHeight: 18 },
  channel: { fontSize: 12, color: theme.colors.inkMuted },
});
