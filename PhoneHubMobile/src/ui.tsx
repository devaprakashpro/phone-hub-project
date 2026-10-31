import React, {createContext, useContext} from 'react';
import {View, Text, Pressable, StyleSheet, ViewStyle} from 'react-native';
import {C, R, Metrics} from './theme';

/* Metrics flow through context so every component scales with the viewport
 * without prop-drilling. App provides it once from useMetrics(). */
export const MetricsCtx = createContext<Metrics | null>(null);
export const useM = (): Metrics => {
  const m = useContext(MetricsCtx);
  if (!m) {
    throw new Error('useM must be used inside <MetricsCtx.Provider>');
  }
  return m;
};

export const Header = ({title, right}: {title: string; right?: string}) => {
  const M = useM();
  return (
    <View style={[s.header, {paddingHorizontal: M.pad + 4, paddingTop: M.s(12)}]}>
      <Text style={[s.brand, {fontSize: M.f(20)}]}>
        <Text style={{color: C.accent}}>✻ </Text>
        {title}
      </Text>
      <Text style={[s.gear, {fontSize: M.f(18)}]}>{right ?? '⚙'}</Text>
    </View>
  );
};

export const Card = ({
  children,
  style,
}: {
  children: React.ReactNode;
  style?: ViewStyle;
}) => {
  const M = useM();
  return <View style={[s.card, {padding: M.s(16), borderRadius: R.lg}, style]}>{children}</View>;
};

export const Pill = ({label, tone = 'accent'}: {label: string; tone?: 'accent' | 'danger' | 'sub'}) => {
  const M = useM();
  const color = tone === 'danger' ? C.danger : tone === 'sub' ? C.sub : C.accent;
  return (
    <View style={[s.pill, {borderColor: color}]}>
      <View style={[s.pillDot, {backgroundColor: color}]} />
      <Text style={[s.pillText, {color, fontSize: M.f(11)}]}>{label}</Text>
    </View>
  );
};

export const Btn = ({
  label,
  onPress,
  kind = 'primary',
}: {
  label: string;
  onPress?: () => void;
  kind?: 'primary' | 'ghost' | 'danger';
}) => {
  const M = useM();
  return (
    <Pressable
      onPress={onPress}
      style={({pressed}) => [
        s.btn,
        {paddingVertical: M.s(14), borderRadius: R.md},
        kind === 'primary' && s.btnPrimary,
        kind === 'ghost' && s.btnGhost,
        kind === 'danger' && s.btnDanger,
        pressed && {opacity: 0.85},
      ]}>
      <Text
        style={[
          s.btnText,
          {fontSize: M.f(15)},
          kind === 'primary' && {color: C.onAccent},
          kind === 'ghost' && {color: C.text},
          kind === 'danger' && {color: C.white},
        ]}>
        {label}
      </Text>
    </Pressable>
  );
};

export const Stat = ({icon, value}: {icon: string; value: string}) => {
  const M = useM();
  return (
    <View style={[s.stat, {paddingVertical: M.s(12), borderRadius: R.md}]}>
      <Text style={{fontSize: M.f(15)}}>{icon}</Text>
      <Text style={[s.statValue, {fontSize: M.f(13)}]}>{value}</Text>
    </View>
  );
};

export const Row = ({
  icon,
  title,
  sub,
  right,
  onPress,
}: {
  icon?: string;
  title: string;
  sub?: string;
  right?: React.ReactNode;
  onPress?: () => void;
}) => {
  const M = useM();
  return (
    <Pressable onPress={onPress} style={[s.row, {paddingVertical: M.s(12)}]}>
      {icon ? (
        <View style={[s.rowIcon, {width: M.s(38), height: M.s(38)}]}>
          <Text style={{fontSize: M.f(16)}}>{icon}</Text>
        </View>
      ) : null}
      <View style={{flex: 1}}>
        <Text style={[s.rowTitle, {fontSize: M.f(14)}]}>{title}</Text>
        {sub ? <Text style={[s.rowSub, {fontSize: M.f(12)}]}>{sub}</Text> : null}
      </View>
      {right}
    </Pressable>
  );
};

const s = StyleSheet.create({
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingBottom: 12,
  },
  brand: {color: C.text, fontWeight: '700'},
  gear: {color: C.sub},
  card: {
    backgroundColor: C.card,
    borderWidth: 1,
    borderColor: C.border,
  },
  pill: {
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 4,
    gap: 6,
  },
  pillDot: {width: 7, height: 7, borderRadius: 4},
  pillText: {fontWeight: '700'},
  btn: {alignItems: 'center'},
  btnPrimary: {backgroundColor: C.accent},
  btnGhost: {backgroundColor: C.cardSoft, borderWidth: 1, borderColor: C.border},
  btnDanger: {backgroundColor: C.danger},
  btnText: {fontWeight: '700'},
  stat: {
    flex: 1,
    backgroundColor: C.cardSoft,
    alignItems: 'center',
    gap: 4,
  },
  statValue: {color: C.text, fontWeight: '600'},
  row: {flexDirection: 'row', alignItems: 'center', gap: 12},
  rowIcon: {
    borderRadius: 10,
    backgroundColor: C.cardSoft,
    alignItems: 'center',
    justifyContent: 'center',
  },
  rowTitle: {color: C.text, fontWeight: '600'},
  rowSub: {color: C.sub, marginTop: 2},
});
