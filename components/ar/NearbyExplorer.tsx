import Ionicons from '@expo/vector-icons/Ionicons';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { NearbyDirectionDial } from './NearbyDirectionDial';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';
import { type ColorSwatch, type NearbyDirection } from '@/lib/nearbyColors';

interface Props {
  active: boolean;
  canEnter: boolean;
  anchor?: ColorSwatch;
  direction: NearbyDirection;
  counts: Record<NearbyDirection, number>;
  canGoBack: boolean;
  onEnter: () => void;
  onLeave: () => void;
  onDirection: (direction: NearbyDirection) => void;
  onBack: () => void;
  onApplyAnchor: () => void;
}

/** Side controls leave the face open; direction choices expand only on request. */
export function NearbyExplorer({ active, canEnter, anchor, direction, counts, canGoBack, onEnter, onLeave, onDirection, onBack, onApplyAnchor }: Props) {
  const { t } = useI18n();
  return (
    <View pointerEvents="box-none" style={styles.container}>
      <Pressable accessibilityRole="button" accessibilityLabel={t(active ? 'ar.explore.free' : 'ar.explore.nearby')}
        accessibilityState={{ disabled: !active && !canEnter }} disabled={!active && !canEnter}
        onPress={() => { if (active) onLeave(); else onEnter(); }}
        style={[styles.switch, !active && !canEnter && styles.disabled]}>
        <View style={[styles.switchIcon, active && styles.switchActive]}>
          <Ionicons name={active ? 'compass-outline' : 'search-outline'} size={19} color="#FFFFFF" />
        </View>
        <Text style={styles.switchLabel}>{t(active ? 'ar.explore.free' : 'ar.explore.nearby')}</Text>
      </Pressable>
      {active && anchor ? (
        <>
          <View style={styles.anchorRow}>
            <Pressable onPress={onApplyAnchor} accessibilityRole="button"
              accessibilityLabel={`${t('ar.explore.applyAnchor')}: ${anchor.product.brand} ${anchor.shade.name}`} style={styles.anchor}>
              <View style={[styles.color, { backgroundColor: anchor.shade.hex }]} />
              <View style={styles.copy}>
                <Text style={styles.small}>{t('ar.arc.anchor')}</Text>
                <Text style={styles.small} numberOfLines={1}>{anchor.shade.name}</Text>
              </View>
            </Pressable>
            {canGoBack ? <Pressable accessibilityRole="button" accessibilityLabel={t('ar.explore.back')} onPress={onBack} style={styles.back}>
              <Ionicons name="arrow-undo-outline" size={18} color="#FFFFFF" />
            </Pressable> : null}
          </View>
          <NearbyDirectionDial key={`${anchor.product.id}:${anchor.shade.id}`} direction={direction} counts={counts} onDirection={onDirection} />
        </>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { height: 226, justifyContent: 'flex-end', zIndex: 3 },
  switch: { position: 'absolute', top: 0, left: 0, width: 44, minHeight: 52, gap: 3, alignItems: 'center', justifyContent: 'center', borderRadius: 22 },
  switchIcon: { width: 32, height: 32, borderRadius: 16, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(30,22,27,0.5)' },
  switchActive: { backgroundColor: theme.colors.rose, borderWidth: 1, borderColor: '#FFFFFF' },
  switchLabel: { width: 60, fontSize: 10, color: '#FFFFFF', fontWeight: '600', textAlign: 'center', textShadowColor: 'rgba(0,0,0,0.75)', textShadowOffset: { width: 0, height: 1 }, textShadowRadius: 3 },
  disabled: { opacity: 0.45 },
  small: { fontSize: 10, color: '#FFFFFF' },
  anchorRow: { flexDirection: 'row', alignItems: 'center', maxWidth: '70%' },
  anchor: { flexShrink: 1, minHeight: 44, flexDirection: 'row', alignItems: 'center', gap: 7, paddingHorizontal: 8, borderRadius: 22, backgroundColor: 'rgba(25,18,22,0.46)' },
  color: { width: 26, height: 26, borderRadius: 13, borderWidth: 1, borderColor: '#FFFFFF' },
  copy: { flexShrink: 1, gap: 2 },
  back: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
});
