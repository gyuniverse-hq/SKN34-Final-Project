import { Platform } from 'react-native';

export const theme = {
  colors: {
    rose: '#C2475E',
    roseDark: '#8F2F42',
    roseSoft: '#F7E3E7',
    ink: '#1C1517',
    inkMuted: '#6E6165',
    inkFaint: '#A3979A',
    surface: '#FFFFFF',
    surfaceAlt: '#F6EEEF',
    card: '#FFFFFF',
    border: '#EADCDF',
    success: '#2F7A55',
    danger: '#B42318',
    warningBg: '#FFF4E5',
    warning: '#9A5B00',
    white: '#FFFFFF',
    black: '#000000',
    overlay: 'rgba(20, 14, 16, 0.6)',
  },
  spacing: { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 },
  radius: { sm: 8, md: 12, lg: 18, pill: 999 },
  font: { caption: 12, small: 13, body: 15, title: 18, h2: 22, h1: 28 },
  shadow: Platform.select({
    ios: { shadowColor: '#3A1F26', shadowOpacity: 0.08, shadowRadius: 12, shadowOffset: { width: 0, height: 4 } },
    android: { elevation: 2 },
    default: { boxShadow: '0 4px 12px rgba(58,31,38,0.08)' },
  }),
} as const;
