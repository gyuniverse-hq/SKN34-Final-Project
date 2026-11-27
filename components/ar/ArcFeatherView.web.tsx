import type { ReactNode } from 'react';
import { View, type ViewStyle } from 'react-native';

export function ArcFeatherView({ width, height, feather = 28, fadeBottom = true, children }: {
  width: number; height: number; feather?: number; fadeBottom?: boolean; children: ReactNode;
}) {
  const sides = 'linear-gradient(to right, transparent, black ' + feather + 'px, black calc(100% - ' + feather + 'px), transparent)';
  const mask = fadeBottom ? sides + ', linear-gradient(to bottom, black, black calc(100% - ' + feather + 'px), transparent)' : sides;
  const style: ViewStyle & { maskImage: string; maskComposite?: string; WebkitMaskImage: string; WebkitMaskComposite?: string } = {
    width, height, maskImage: mask, WebkitMaskImage: mask,
    ...(fadeBottom && { maskComposite: 'intersect', WebkitMaskComposite: 'source-in' }),
  };
  return <View style={style}>{children}</View>;
}
