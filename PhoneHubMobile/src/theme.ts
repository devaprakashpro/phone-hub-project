import {useWindowDimensions} from 'react-native';
import {useSafeAreaInsets, EdgeInsets} from 'react-native-safe-area-context';

// Shared palette — kept identical to the desktop app (desktop/phonehub_desktop.py
// → PAL) so phone and laptop read as one product. Indigo "aurora" dark theme.
export const C = {
  bg: '#0b0d14', // deep ink base
  bgElev: '#10131d',
  card: '#151926',
  cardSoft: '#1b2030',
  border: '#272d3f',
  accent: '#7c8bff', // periwinkle / indigo
  accentDim: '#4b56b8',
  accentSoft: 'rgba(124,139,255,0.14)',
  onAccent: '#0a0e22', // text/icon sitting on top of an accent fill
  text: '#eef1f9',
  sub: '#9098ad',
  faint: '#5a6178',
  danger: '#ff5d72',
  warn: '#ffb454',
  white: '#ffffff',
};

export const R = {sm: 10, md: 14, lg: 18, xl: 24};

/**
 * Everything size-sensitive is derived here from the live viewport so the UI
 * scales smoothly from a small phone to a tablet/landscape window. Components
 * read `M` for dynamic numbers; StyleSheet keeps only the cosmetic constants.
 */
export type Metrics = {
  width: number;
  height: number;
  insets: EdgeInsets;
  isWide: boolean;            // tablet / landscape — constrain & widen
  contentMax: number;        // max content column width
  pad: number;               // outer gutter
  gap: number;               // inter-card gap
  s: (n: number) => number;  // scale a base-390 dp value
  f: (n: number) => number;  // scale a font size (gentler curve)
  previewH: number;          // hero/preview block height
  tabBarH: number;           // bottom nav height (excl. inset)
};

export function useMetrics(): Metrics {
  const {width, height} = useWindowDimensions();
  const insets = useSafeAreaInsets();
  const isWide = width >= 680;

  // Scale relative to a 390dp baseline, clamped so text never gets silly.
  const raw = width / 390;
  const k = Math.min(Math.max(raw, 0.86), isWide ? 1.15 : 1.28);
  const s = (n: number) => Math.round(n * k);
  // Fonts use a gentler curve so large screens don't get huge type.
  const fk = Math.min(Math.max(0.5 + raw * 0.5, 0.92), 1.18);
  const f = (n: number) => Math.round(n * fk);

  const contentMax = isWide ? 560 : width;
  const pad = isWide ? 20 : s(14);
  const gap = s(14);
  // Hero fills a healthy slice of the viewport but never dominates a tablet.
  const previewH = Math.round(Math.min(Math.max(height * 0.34, 240), 380));
  const tabBarH = s(58);

  return {width, height, insets, isWide, contentMax, pad, gap, s, f, previewH, tabBarH};
}
