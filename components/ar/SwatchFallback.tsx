import { StyleSheet, Text, View } from 'react-native';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';
import { useMakeupStore } from '@/store/makeupStore';

/** Static face illustration used when live camera try-on isn't available. */
export function SwatchFallback({ message }: { message?: string }) {
  const { t } = useI18n();
  const makeup = useMakeupStore((s) => s.makeup);
  const lip = makeup.lip;
  const blush = makeup.blush;
  const eye = makeup.eyeshadow;

  return (
    <View style={styles.wrap}>
      <Text style={styles.title}>{t('ar.previewTitle')}</Text>
      {message ? <Text style={styles.hint}>{message}</Text> : null}
      <View style={styles.face} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
        {eye ? (
          <>
            <View style={[styles.eye, { left: 34, backgroundColor: eye.hex, opacity: 0.25 + eye.intensity * 0.5 }]} />
            <View style={[styles.eye, { right: 34, backgroundColor: eye.hex, opacity: 0.25 + eye.intensity * 0.5 }]} />
          </>
        ) : null}
        {blush ? (
          <>
            <View style={[styles.cheek, { left: 18, backgroundColor: blush.hex, opacity: 0.2 + blush.intensity * 0.5 }]} />
            <View style={[styles.cheek, { right: 18, backgroundColor: blush.hex, opacity: 0.2 + blush.intensity * 0.5 }]} />
          </>
        ) : null}
        <View
          style={[
            styles.lip,
            { backgroundColor: lip?.hex ?? '#D9A6A0', opacity: lip ? 0.35 + lip.intensity * 0.6 : 0.5 },
          ]}
        />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24, backgroundColor: theme.colors.surfaceAlt },
  title: { fontSize: theme.font.title, fontWeight: '700', color: theme.colors.ink },
  hint: { fontSize: theme.font.small, color: theme.colors.inkMuted, textAlign: 'center', marginTop: 6, marginBottom: 8 },
  face: { width: 190, height: 240, borderRadius: 95, backgroundColor: '#F1D3C3', marginTop: 20 },
  eye: { position: 'absolute', top: 82, width: 44, height: 16, borderRadius: 8 },
  cheek: { position: 'absolute', top: 128, width: 44, height: 30, borderRadius: 16 },
  lip: { position: 'absolute', bottom: 52, left: 62, right: 62, height: 24, borderRadius: 12 },
});
