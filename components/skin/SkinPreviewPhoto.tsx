import { useMemo } from 'react';
import { StyleSheet, View } from 'react-native';
import { WebView } from 'react-native-webview';
import { skinPreviewHtml } from '@/lib/skinPreview';
import type { SkinConcern } from '@/types';
import type { SkinPreview } from '@/types/skin';

/** A local data-only document: no scripts, network, persistent cache or photo files. */
export function SkinPreviewPhoto({ preview, active }: { preview: SkinPreview; active: SkinConcern }) {
  const source = useMemo(() => ({ html: skinPreviewHtml(preview, active) }), [preview, active]);
  return <View pointerEvents="none" style={[styles.frame, { aspectRatio: preview.width / preview.height }]}>
    <WebView source={source} javaScriptEnabled={false} cacheEnabled={false} scrollEnabled={false}
      originWhitelist={['about:blank', 'data:*']} allowFileAccess={false} style={styles.web} />
  </View>;
}
const styles = StyleSheet.create({
  frame: { width: '100%', overflow: 'hidden', borderRadius: 16, backgroundColor: '#F5EFF0' },
  web: { flex: 1, backgroundColor: 'transparent' },
});
