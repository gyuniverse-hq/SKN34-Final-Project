import { Platform } from 'react-native';

/** VISHUE v1.2 palette: ivory surfaces, burgundy primary, rose accent. */
export const theme = {
  colors: {
    rose: '#782C4C',
    roseDark: '#5D213B',
    roseSoft: '#F8EDF1',
    accent: '#B6547E',
    ink: '#33242D',
    inkMuted: '#5C5058',
    inkFaint: '#95828E',
    surface: '#FFFAF9',
    surfaceAlt: '#F3E6EA',
    card: '#FFFFFF',
    border: '#E8DFE2',
    chip: '#F5EFF0',
    cream: '#F9EFE8',
    success: '#3E846B',
    danger: '#B42318',
    warningBg: '#FFF4E5',
    warning: '#9A5B00',
    white: '#FFFFFF',
    black: '#000000',
    overlay: 'rgba(26, 17, 24, 0.6)',
  },
  spacing: { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 },
  radius: { sm: 8, md: 12, lg: 18, pill: 999 },
  font: { caption: 12, small: 13, body: 15, title: 18, h2: 22, h1: 28 },
  fontFamily: {
    display: Platform.select({ ios: 'Georgia', android: 'serif', default: 'Georgia, serif' }),
  },
  /** Minimum touch target (iOS HIG 44pt, Material 48dp). */
  hitTarget: 44,
  shadow: Platform.select({
    ios: { shadowColor: '#532F3E', shadowOpacity: 0.08, shadowRadius: 12, shadowOffset: { width: 0, height: 4 } },
    android: { elevation: 2 },
    default: { boxShadow: '0 4px 12px rgba(83,47,62,0.08)' },
  }),
} as const;

export const TAB_BAR_STYLE = { backgroundColor: theme.colors.card, borderTopColor: theme.colors.border };
