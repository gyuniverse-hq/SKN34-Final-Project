import { MaskedView } from '@expo/ui/community/masked-view';
import { useId, type ReactNode } from 'react';
import Svg, { Defs, LinearGradient, Mask, Rect, Stop } from 'react-native-svg';

/** Alpha feathering reveals the live camera underneath, without a painted edge overlay. */
export function ArcFeatherView({ width, height, feather = 28, fadeBottom = true, children }: {
  width: number; height: number; feather?: number; fadeBottom?: boolean; children: ReactNode;
}) {
  const id = useId().replace(/:/g, '');
  return (
    <MaskedView style={{ width, height }} maskElement={
      <Svg width={width} height={height} pointerEvents="none">
        <Defs>
          <LinearGradient id={id + 'sides'} x1="0" y1="0" x2="1" y2="0">
            <Stop offset="0" stopColor="white" stopOpacity="0" />
            <Stop offset={feather / width} stopColor="white" />
            <Stop offset={1 - feather / width} stopColor="white" />
            <Stop offset="1" stopColor="white" stopOpacity="0" />
          </LinearGradient>
          {fadeBottom ? <>
            <LinearGradient id={id + 'bottom'} x1="0" y1="0" x2="0" y2="1">
              <Stop offset="0" stopColor="white" />
              <Stop offset={1 - feather / height} stopColor="white" />
              <Stop offset="1" stopColor="white" stopOpacity="0" />
            </LinearGradient>
            <Mask id={id + 'mask'} x="0" y="0" width={width} height={height} maskUnits="userSpaceOnUse">
              <Rect width={width} height={height} fill={'url(#' + id + 'bottom)'} />
            </Mask>
          </> : null}
        </Defs>
        <Rect width={width} height={height} fill={'url(#' + id + 'sides)'}
          mask={fadeBottom ? 'url(#' + id + 'mask)' : undefined} />
      </Svg>
    }>{children}</MaskedView>
  );
}
