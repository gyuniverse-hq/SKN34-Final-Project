import Constants, { ExecutionEnvironment } from 'expo-constants';
import { useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Platform, StyleSheet, View } from 'react-native';
import { WebView } from 'react-native-webview';
import { theme } from '@/constants/theme';

interface Props { videoId: string; startSeconds?: number; title: string }

export function YoutubePlayer({ videoId, startSeconds = 0, title }: Props) {
  const [focused, setFocused] = useState(false);
  useFocusEffect(useCallback(() => {
    setFocused(true);
    return () => setFocused(false);
  }, []));
  const validId = /^[A-Za-z0-9_-]{11}$/.test(videoId);
  const start = Number.isFinite(startSeconds) && startSeconds > 0 ? Math.floor(startSeconds) : 0;
  const appId = Constants.executionEnvironment === ExecutionEnvironment.StoreClient
    ? 'host.exp.exponent'
    : Platform.OS === 'ios' ? Constants.expoConfig?.ios?.bundleIdentifier : Constants.expoConfig?.android?.package;
  const referer = appId ? `https://${appId.toLowerCase()}` : undefined;
  const uri = `https://www.youtube.com/embed/${videoId}?playsinline=1&start=${start}`;

  return (
    <View style={styles.container}>
      {focused && validId && referer ? <WebView
        accessibilityLabel={title}
        source={{ uri, headers: { Referer: referer } }}
        style={styles.player}
        javaScriptEnabled
        domStorageEnabled
        allowsInlineMediaPlayback
        allowsFullscreenVideo
        mediaPlaybackRequiresUserAction
      /> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { width: '100%', aspectRatio: 16 / 9, minHeight: 200, borderRadius: 20, overflow: 'hidden', backgroundColor: theme.colors.black },
  player: { flex: 1, backgroundColor: theme.colors.black },
});
