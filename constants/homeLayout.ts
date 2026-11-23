import { theme } from '@/constants/theme';

export const homeLayout = {
  displayFont: theme.fontFamily.display,
  background: '#FFFAF8',
  blush: '#F4E8E7',
  headerHeight: 58,
  gutter: 15,
  productGap: 9,
  categorySize: 56,
  maxWidth: 680,
} as const;

/** Tracking −30, expressed in native layout units for the given font size. */
export function homeType(fontSize: number) {
  return { fontSize, letterSpacing: -0.03 * fontSize };
}

export const homeHeading = {
  ...homeType(16),
  fontWeight: '600',
  lineHeight: 23,
  color: theme.colors.ink,
} as const;

export const tabTitle = {
  ...homeType(26),
  fontWeight: '600',
  color: theme.colors.roseDark,
} as const;
