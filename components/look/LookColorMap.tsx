import { StyleSheet, Text, View } from 'react-native';
import Svg, { Circle, Defs, Ellipse, G, Line, Path, RadialGradient, Stop, Text as SvgText } from 'react-native-svg';
import { theme } from '@/constants/theme';
import type { LookPreviewZone } from '@/lib/lookPreview';
import type { MakeupZone } from '@/types';

type Props = {
  zones: LookPreviewZone[];
  caption: string;
  onZonePress?: (zone: MakeupZone) => void;
};

// Side labels share two fixed columns in the SVG coordinate space.
export const LOOK_MAP_MARKERS: Record<MakeupZone, { x: number; y: number; targetX: number; targetY: number }> = {
  foundation: { x: 32, y: 59, targetX: 137, targetY: 87 },
  brow: { x: 32, y: 103, targetX: 127, targetY: 109 },
  eyeliner: { x: 32, y: 148, targetX: 119, targetY: 136 },
  contour: { x: 32, y: 203, targetX: 116, targetY: 204 },
  lip: { x: 32, y: 248, targetX: 147, targetY: 204 },
  eyeshadow: { x: 288, y: 85, targetX: 193, targetY: 123 },
  mascara: { x: 288, y: 131, targetX: 208, targetY: 135 },
  highlighter: { x: 288, y: 176, targetX: 162, targetY: 156 },
  blush: { x: 288, y: 223, targetX: 201, targetY: 181 },
};

export function LookColorMap({ zones, caption, onZonePress }: Props) {
  const colors = new Map(zones.map((zone) => [zone.zone, zone.hex]));
  const cheek = colors.get('blush');
  const highlight = colors.get('highlighter');
  const contour = colors.get('contour');

  return (
    <View style={styles.wrap}>
      <View style={styles.map} accessible={false}>
        <Svg width="100%" height="100%" viewBox="0 0 320 282">
          <Defs>
            <RadialGradient id="lookSkin" cx="49%" cy="42%" rx="60%" ry="62%">
              <Stop offset="0" stopColor="#FFF1E6" />
              <Stop offset="0.72" stopColor={colors.get('foundation') ?? '#F2D4BE'} stopOpacity={0.66} />
              <Stop offset="1" stopColor="#C9957E" />
            </RadialGradient>
            <RadialGradient id="lookCheek">
              <Stop offset="0" stopColor={cheek ?? '#DD897F'} stopOpacity={cheek ? 0.58 : 0.23} />
              <Stop offset="1" stopColor={cheek ?? '#DD897F'} stopOpacity={0} />
            </RadialGradient>
            <RadialGradient id="lookHighlight">
              <Stop offset="0" stopColor={highlight ?? '#FFF3DF'} stopOpacity={0.8} />
              <Stop offset="1" stopColor={highlight ?? '#FFF3DF'} stopOpacity={0} />
            </RadialGradient>
          </Defs>
          <Path d="M88 159C74 122 72 57 109 32C143 7 203 17 224 52C244 81 240 131 230 163Z" fill="#392822" />
          <Path d="M137 222C137 247 134 257 116 266L105 282H215L204 266C186 257 183 246 183 222Z" fill="#E4BEA9" />
          <Path d="M143 234Q160 252 178 234L185 250Q163 263 136 249Z" fill="#B17B66" opacity={0.33} />
          <Path d="M98 135C76 118 77 153 89 166C93 171 97 169 101 166M222 135C244 118 243 153 231 166C227 171 223 169 219 166" fill="#E6BEA8" stroke="#C8957E" />
          <Path d="M94 104C95 70 122 48 156 47C196 47 220 69 226 104L226 145C225 179 209 211 178 236C166 246 154 246 142 236C111 211 95 179 94 145Z" fill="#EED0BA" />
          <Path d="M94 104C95 70 122 48 156 47C196 47 220 69 226 104L226 145C225 179 209 211 178 236C166 246 154 246 142 236C111 211 95 179 94 145Z" fill="url(#lookSkin)" stroke="#C99781" strokeWidth={0.8} />
          <Path d="M89 122C79 74 105 34 145 34C179 29 210 42 222 70C229 85 232 106 227 125C223 108 217 94 209 79C189 80 160 72 144 55C134 75 112 91 94 104Z" fill="#42302A" />
          <Path d="M91 97C98 62 112 47 145 40M154 42C178 39 203 51 216 76" fill="none" stroke="#62463B" strokeWidth={2} opacity={0.7} />
          {contour ? <Path d="M100 169Q108 198 128 215M220 169Q212 198 192 215" fill="none" stroke={contour} strokeWidth={12} strokeLinecap="round" opacity={0.19} /> : null}
          <Ellipse cx={117} cy={176} rx={26} ry={17} fill="url(#lookCheek)" />
          <Ellipse cx={203} cy={176} rx={26} ry={17} fill="url(#lookCheek)" />
          <Ellipse cx={160} cy={150} rx={10} ry={24} fill="url(#lookHighlight)" />
          <Path d="M151 143C151 155 148 166 145 171C146 176 152 176 154 175Q160 181 166 175C169 176 174 175 175 171C171 165 170 157 169 147" fill="none" stroke="#BA826D" strokeWidth={1.2} strokeLinecap="round" opacity={0.75} />
          {[false, true].map((mirror) => (
            <G key={String(mirror)} transform={mirror ? 'translate(320 0) scale(-1 1)' : undefined}>
              <Path d="M103 113C109 102 125 100 142 108L143 113C128 107 114 108 103 115Z" fill={colors.get('brow') ?? '#644A40'} />
              <Path d="M103 133C111 118 128 118 144 133C128 127 117 126 103 137Z" fill={colors.get('eyeshadow') ?? '#C7837D'} opacity={0.52} />
              <Path d="M105 137C116 127 131 127 144 138C132 147 115 147 105 137Z" fill="#FFFBF6" stroke="#B68475" strokeWidth={0.8} />
              <Circle cx={125} cy={137} r={7} fill="#795042" />
              <Circle cx={125} cy={137} r={3.9} fill="#312321" />
              <Circle cx={123} cy={135} r={1.5} fill="#FFF5EC" />
              <Path d="M101 133L105 137C116 127 131 127 144 138" fill="none" stroke={colors.get('eyeliner') ?? '#4B332E'} strokeWidth={1.5} strokeLinecap="round" />
              <Path d="M110 134L106 128M115 132L112 125M121 131L119 125" fill="none" stroke={colors.get('mascara') ?? '#4B332E'} strokeWidth={1.1} strokeLinecap="round" />
            </G>
          ))}
          <Path d="M136 204Q145 195 153 196Q160 200 167 196Q175 195 184 204Q173 216 160 216Q147 216 136 204Z" fill={colors.get('lip') ?? '#C97879'} stroke="#A95E60" strokeWidth={0.9} />
          <Path d="M137 204Q147 202 154 205Q160 207 166 205Q175 202 183 204" fill="none" stroke="#934D53" strokeWidth={1} />
          <Path d="M150 210Q160 214 170 210" fill="none" stroke="#FFF0E4" strokeWidth={1.2} opacity={0.54} strokeLinecap="round" />
          {zones.map(({ zone, index, hex }) => {
            const { x, y, targetX, targetY } = LOOK_MAP_MARKERS[zone];
            return (
              <G
                key={zone}
                onPress={onZonePress ? () => onZonePress(zone) : undefined}
                accessibilityRole={onZonePress ? 'button' : undefined}
                accessibilityLabel={onZonePress ? String(index) : undefined}>
                <Line x1={x} y1={y} x2={targetX} y2={targetY} stroke="#7B6063" strokeWidth={1} opacity={0.67} />
                <Circle cx={targetX} cy={targetY} r={3.5} fill={hex} stroke="#FFF8F5" strokeWidth={1.2} />
                <Circle cx={x} cy={y} r={16} fill="transparent" />
                <Circle cx={x} cy={y} r={12} fill={theme.colors.ink} stroke={theme.colors.white} strokeWidth={1.5} />
                <SvgText x={x} y={y + 4.3} fill={theme.colors.white} fontSize={12} fontWeight="700" textAnchor="middle">{index}</SvgText>
              </G>
            );
          })}
        </Svg>
      </View>
      <Text style={styles.caption}>{caption}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { alignItems: 'center', gap: theme.spacing.sm },
  map: { width: '100%', maxWidth: 360, aspectRatio: 320 / 282, backgroundColor: '#F5EDE8', borderRadius: theme.radius.lg, overflow: 'hidden' },
  caption: { color: theme.colors.inkMuted, textAlign: 'center', fontSize: theme.font.caption },
});
