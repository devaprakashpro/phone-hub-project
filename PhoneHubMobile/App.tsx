/**
 * PhoneHub — React Native companion (multi-tab, fully responsive UI).
 * Scan-to-sync + phone-initiated mirror. JS owns UI; native `Hub` owns the
 * WebSocket + H.264 mirror stream. Every size is derived from the live
 * viewport (see src/theme.ts → useMetrics), so it scales phone→tablet→landscape.
 */
import React, {
  useEffect,
  useState,
  useRef,
  useCallback,
  useMemo,
  Suspense,
} from 'react';
import {
  View,
  Text,
  ScrollView,
  Pressable,
  StyleSheet,
  StatusBar,
  PermissionsAndroid,
  Platform,
  NativeModules,
  NativeEventEmitter,
  AppState,
  Alert,
  Modal,
  TextInput,
} from 'react-native';
import {SafeAreaProvider} from 'react-native-safe-area-context';
import {Camera} from 'react-native-camera-kit';
import {C, R, useMetrics, Metrics} from './src/theme';
import {MetricsCtx, useM, Header, Card, Pill, Btn, Stat} from './src/ui';

const {Hub} = NativeModules;
// Guard: if the native module failed to link we still want a usable shell
// instead of a hard crash at module-eval time.
const hubEvents = Hub ? new NativeEventEmitter(Hub) : null;

type CState = 'DISCONNECTED' | 'CONNECTING' | 'NEED_PIN' | 'PAIRED' | 'READY';
type Tab = 'dash' | 'devices' | 'files' | 'alerts';

export default function App() {
  return (
    <SafeAreaProvider>
      <Root />
    </SafeAreaProvider>
  );
}

function Root() {
  const M = useMetrics();
  return (
    <MetricsCtx.Provider value={M}>
      <Shell />
    </MetricsCtx.Provider>
  );
}

function Shell() {
  const M = useM();
  const st = useMemo(() => makeStyles(M), [M]);
  const [tab, setTab] = useState<Tab>('dash');
  const [state, setState] = useState<CState>('DISCONNECTED');
  const [peer, setPeer] = useState('');
  const [mirroring, setMirroring] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [manual, setManual] = useState(false);
  const [mHost, setMHost] = useState('');
  const [mPin, setMPin] = useState('');
  const pinRef = useRef('');
  const connected = state === 'READY' || state === 'PAIRED';

  useEffect(() => {
    if (!hubEvents) return;
    const s = hubEvents.addListener('state', (v: CState) => setState(v));
    const p = hubEvents.addListener('needPin', () => {
      if (pinRef.current) Hub.sendPin(pinRef.current);
    });
    // Always-on ecosystem: silently re-link to the laptop from a previous
    // pairing, and re-check whenever the app returns to the foreground.
    Hub?.autoConnect?.().catch(() => {});
    const appSub = AppState.addEventListener('change', st => {
      if (st === 'active') Hub?.autoConnect?.().catch(() => {});
    });
    return () => {
      s.remove();
      p.remove();
      appSub.remove();
    };
  }, []);

  const startScan = useCallback(async () => {
    if (Platform.OS === 'android') {
      const g = await PermissionsAndroid.request(
        PermissionsAndroid.PERMISSIONS.CAMERA,
      );
      if (g !== PermissionsAndroid.RESULTS.GRANTED) return;
    }
    setScanning(true);
  }, []);

  const connectTo = useCallback((host: string, port: number, pin: string) => {
    pinRef.current = String(pin ?? '');
    setPeer(`${host}:${port}`);
    if (!Hub?.connect) {
      Alert.alert('Native module missing', 'Hub.connect is unavailable.');
      return;
    }
    Hub.connect(String(host), Number(port) || 8766);
  }, []);

  const onRead = useCallback(
    (e: any) => {
      const raw = e?.nativeEvent?.codeStringValue;
      if (!raw) return;
      setScanning(false);
      try {
        const {host, port, pin} = JSON.parse(raw);
        connectTo(String(host), Number(port) || 8766, String(pin ?? ''));
      } catch {
        // QR wasn't our JSON payload — show it so the user knows it scanned.
        Alert.alert('Unrecognised QR', String(raw).slice(0, 120));
      }
    },
    [connectTo],
  );

  const toggleMirror = useCallback(() => {
    if (mirroring) {
      Hub?.stopMirror();
      setMirroring(false);
    } else {
      Hub?.startMirror();
      setMirroring(true);
    }
  }, [mirroring]);

  if (scanning) {
    return (
      <View style={st.scanRoot}>
        <StatusBar barStyle="light-content" backgroundColor="#000" />
        {/* Camera is a React.lazy component — it MUST sit inside a Suspense
            boundary or mounting it throws and the scanner never appears. */}
        <Suspense
          fallback={
            <View style={[StyleSheet.absoluteFill, st.scanLoading]}>
              <Text style={st.scanHint}>Starting camera…</Text>
            </View>
          }>
          <Camera style={StyleSheet.absoluteFill} scanBarcode onReadCode={onRead} />
        </Suspense>
        <View style={st.scanOverlay} pointerEvents="none">
          <View style={st.reticle} />
          <Text style={st.scanHint}>Point at the QR on your laptop</Text>
        </View>
        <Pressable
          style={[st.cancel, {bottom: M.insets.bottom + M.s(32)}]}
          onPress={() => setScanning(false)}>
          <Text style={{color: C.text, fontWeight: '700'}}>Cancel</Text>
        </Pressable>
      </View>
    );
  }

  const statusLabel: Record<CState, string> = {
    DISCONNECTED: 'Idle',
    CONNECTING: 'Connecting…',
    NEED_PIN: 'Pairing…',
    PAIRED: 'Paired',
    READY: 'Ready',
  };

  return (
    <View style={[st.root, {paddingTop: M.insets.top}]}>
      <StatusBar barStyle="light-content" backgroundColor={C.bg} />
      <Header title="PhoneHub" />
      <ScrollView
        contentContainerStyle={st.scroll}
        showsVerticalScrollIndicator={false}>
        <View style={st.column}>
          {tab === 'dash' && (
            <Dash
              status={statusLabel[state]}
              connected={connected}
              mirroring={mirroring}
              onMirror={toggleMirror}
              onScan={startScan}
              onManual={() => setManual(true)}
            />
          )}
          {tab === 'devices' && (
            <Devices connected={connected} peer={peer} onMirror={toggleMirror} onScan={startScan} />
          )}
          {tab === 'files' && <Files connected={connected} onScan={startScan} />}
          {tab === 'alerts' && <Alerts connected={connected} />}
        </View>
      </ScrollView>
      <TabBar tab={tab} setTab={setTab} />

      <Modal
        visible={manual}
        transparent
        animationType="fade"
        onRequestClose={() => setManual(false)}>
        <View style={st.modalWrap}>
          <View style={st.modalCard}>
            <Text style={st.cardTitle}>Connect manually</Text>
            <Text style={st.rowSub}>
              Enter the laptop's IP and the PIN shown under the QR.
            </Text>
            <TextInput
              style={st.input}
              placeholder="192.168.1.6"
              placeholderTextColor={C.faint}
              autoCapitalize="none"
              keyboardType="numbers-and-punctuation"
              value={mHost}
              onChangeText={setMHost}
            />
            <TextInput
              style={st.input}
              placeholder="PIN (6 digits)"
              placeholderTextColor={C.faint}
              keyboardType="number-pad"
              value={mPin}
              onChangeText={setMPin}
            />
            <View style={{flexDirection: 'row', gap: 10, marginTop: M.s(6)}}>
              <View style={{flex: 1}}>
                <Btn label="Cancel" kind="ghost" onPress={() => setManual(false)} />
              </View>
              <View style={{flex: 1}}>
                <Btn
                  label="Connect"
                  onPress={() => {
                    const host = mHost.trim();
                    if (!host) return;
                    setManual(false);
                    connectTo(host, 8766, mPin.trim());
                  }}
                />
              </View>
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
}

/* ---------------- Dashboard / Mirror ---------------- */
function Dash({status, connected, mirroring, onMirror, onScan, onManual}: any) {
  const M = useM();
  const st = useMemo(() => makeStyles(M), [M]);
  return (
    <Card style={{padding: M.s(14)}}>
      <View style={st.cardHead}>
        <Text style={st.cardTitle}>
          <Text style={{color: C.accent}}>✻ </Text>PhoneHub
        </Text>
        {mirroring ? (
          <Pill label="Mirroring Active" />
        ) : (
          <Pill label={status} tone={connected ? 'accent' : 'sub'} />
        )}
      </View>

      <View style={st.preview}>
        {connected ? (
          <>
            <Text style={st.previewBig}>{mirroring ? '◉' : '▶'}</Text>
            <Text style={st.previewText}>
              {mirroring ? 'Your screen is streaming to the laptop' : 'Ready to cast'}
            </Text>
          </>
        ) : (
          <>
            <Text style={st.previewBig}>⌁</Text>
            <Text style={st.previewText}>{status === 'Idle' ? 'Not connected' : status}</Text>
            <View style={{marginTop: M.s(14), width: '70%', maxWidth: 320}}>
              <Btn label="Scan to connect" onPress={onScan} />
            </View>
            <Pressable onPress={onManual} style={{marginTop: M.s(12)}}>
              <Text style={{color: C.accent, fontWeight: '700', fontSize: M.f(13)}}>
                Enter IP manually
              </Text>
            </Pressable>
          </>
        )}
      </View>

      {connected && (
        <>
          <View style={st.toolRow}>
            <Tool icon="⟳" label="Rotate" />
            <Tool icon="◳" label="Capture" />
            <Tool icon="⇲" label="Cast" onPress={onMirror} active={mirroring} />
          </View>
          <View style={st.metricRow}>
            <Metric label="LATENCY" value="—" />
            <Metric label="BITRATE" value="—" />
          </View>
          <Btn
            label={mirroring ? '◉  Stop Mirroring' : '⇲  Start Mirroring'}
            kind={mirroring ? 'danger' : 'primary'}
            onPress={onMirror}
          />
        </>
      )}
    </Card>
  );
}

const Tool = ({icon, label, onPress, active}: any) => {
  const M = useM();
  const st = useMemo(() => makeStyles(M), [M]);
  return (
    <Pressable
      onPress={onPress}
      style={[st.tool, active && {borderColor: C.accent, backgroundColor: C.accentSoft}]}>
      <Text style={{fontSize: M.f(18), color: active ? C.accent : C.text}}>{icon}</Text>
      <Text style={st.toolLabel}>{label}</Text>
    </Pressable>
  );
};
const Metric = ({label, value}: any) => {
  const M = useM();
  const st = useMemo(() => makeStyles(M), [M]);
  return (
    <View style={{flex: 1}}>
      <Text style={st.metricLabel}>{label}</Text>
      <Text style={st.metricValue}>{value}</Text>
    </View>
  );
};

/* ---------------- Devices ---------------- */
function Devices({connected, peer, onMirror, onScan}: any) {
  const M = useM();
  const st = useMemo(() => makeStyles(M), [M]);
  return (
    <Card style={{gap: M.s(14)}}>
      <View style={st.cardHead}>
        <Text style={st.cardTitle}>Active Link</Text>
        <Pill label={connected ? 'SECURE' : 'OFFLINE'} tone={connected ? 'accent' : 'sub'} />
      </View>

      <View style={st.deviceCard}>
        <View style={st.deviceTop}>
          <Text style={{fontSize: M.f(26)}}>📱</Text>
          <View style={{flex: 1, marginLeft: 12}}>
            <Text style={st.deviceName}>{connected ? peer || 'Laptop' : 'No device'}</Text>
            <Text style={st.rowSub}>Primary link · v0.1</Text>
          </View>
          <Pill label={connected ? 'ONLINE' : 'OFFLINE'} tone={connected ? 'accent' : 'sub'} />
        </View>
        <View style={st.statRow}>
          <Stat icon="🔋" value="—" />
          <Stat icon="📶" value="—" />
          <Stat icon="🖴" value="—" />
        </View>
        <View style={{flexDirection: 'row', gap: 10}}>
          <View style={{flex: 1}}>
            <Btn
              label={connected ? 'Mirror Screen' : 'Scan to connect'}
              onPress={connected ? onMirror : onScan}
            />
          </View>
          <Pressable style={st.refresh}>
            <Text style={{color: C.accent, fontSize: M.f(18)}}>⟳</Text>
          </Pressable>
        </View>
      </View>

      <Pressable style={st.addBtn} onPress={onScan}>
        <Text style={{color: C.sub, fontWeight: '600'}}>＋  Add new device</Text>
      </Pressable>
    </Card>
  );
}

/* ---------------- Files ---------------- */
function Files({connected, onScan}: any) {
  const M = useM();
  const st = useMemo(() => makeStyles(M), [M]);
  return (
    <Card style={{gap: M.s(14)}}>
      <Text style={st.cardTitle}>
        <Text style={{color: C.accent}}>✻ </Text>Files
      </Text>

      <View style={st.linkCard}>
        <View style={{flex: 1}}>
          <Text style={st.rowTitle}>Precision Link</Text>
          <Text style={st.rowSub}>
            {connected ? 'Connected to laptop' : 'Waiting for desktop…'}
          </Text>
        </View>
        <Pressable style={st.scanChip} onPress={onScan}>
          <Text style={{color: C.accent, fontWeight: '700', fontSize: M.f(12)}}>Scan Code</Text>
        </Pressable>
      </View>

      <Pressable
        style={st.sendBox}
        onPress={() =>
          connected ? Hub?.sendFile?.() : Alert.alert('Not connected', 'Pair with the laptop first.')
        }>
        <Text style={{fontSize: M.f(26)}}>📤</Text>
        <Text style={[st.rowTitle, {marginTop: 6}]}>Send File to Laptop</Text>
        <Text style={st.rowSub}>Tap to pick a file from storage</Text>
      </Pressable>

      <Btn
        label="📋  Send Clipboard to Laptop"
        kind="ghost"
        onPress={() =>
          connected ? Hub?.sendClipboard?.() : Alert.alert('Not connected', 'Pair with the laptop first.')
        }
      />

      <Text style={st.section}>Recent Transfers</Text>
      <Text style={st.empty}>No transfers yet</Text>
    </Card>
  );
}

/* ---------------- Alerts ---------------- */
function Alerts({connected}: any) {
  const M = useM();
  const st = useMemo(() => makeStyles(M), [M]);
  const [perms, setPerms] = useState({notifications: false, control: false});

  const refresh = useCallback(() => {
    Hub?.getPermissions?.()
      .then((p: any) => setPerms({notifications: !!p?.notifications, control: !!p?.control}))
      .catch(() => {});
  }, []);

  useEffect(() => {
    refresh();
    // Re-check when the user comes back from the system settings screen.
    const sub = AppState.addEventListener('change', s => {
      if (s === 'active') refresh();
    });
    return () => sub.remove();
  }, [refresh]);

  return (
    <Card style={{gap: M.s(14)}}>
      <Text style={st.cardTitle}>
        <Text style={{color: C.accent}}>✻ </Text>Alerts
      </Text>
      <View style={st.linkCard}>
        <Text style={{fontSize: M.f(22)}}>🔗</Text>
        <View style={{flex: 1, marginLeft: 10}}>
          <Text style={[st.rowSub, {color: connected ? C.accent : C.sub, fontWeight: '700'}]}>
            {connected ? 'CONNECTED' : 'DISCONNECTED'}
          </Text>
          <Text style={st.rowTitle}>{connected ? 'Laptop link' : 'No phone link'}</Text>
        </View>
        {connected ? <Text style={{color: C.accent}}>((•))</Text> : null}
      </View>

      <Text style={st.section}>Phone Powers</Text>
      <Perm
        title="Notification mirroring"
        desc="Show this phone's notifications on the laptop."
        ok={perms.notifications}
        onPress={() => Hub?.openNotificationAccess()}
      />
      <Perm
        title="Keyboard & mouse control"
        desc="Let the laptop tap, swipe and type while mirroring."
        ok={perms.control}
        onPress={() => Hub?.openAccessibilitySettings()}
      />

      <Text style={st.section}>Notifications</Text>
      <Text style={st.empty}>No notifications yet</Text>
    </Card>
  );
}

const Perm = ({title, desc, ok, onPress}: any) => {
  const M = useM();
  const st = useMemo(() => makeStyles(M), [M]);
  return (
    <View style={st.alertBox}>
      <View style={{flexDirection: 'row', alignItems: 'center'}}>
        <View style={{flex: 1}}>
          <Text style={st.rowTitle}>{title}</Text>
          <Text style={st.rowSub}>{desc}</Text>
        </View>
        <Pill label={ok ? 'ON' : 'OFF'} tone={ok ? 'accent' : 'sub'} />
      </View>
      {!ok && (
        <View style={{marginTop: M.s(10)}}>
          <Btn label="Enable" onPress={onPress} />
        </View>
      )}
    </View>
  );
};

/* ---------------- Tab bar ---------------- */
function TabBar({tab, setTab}: {tab: Tab; setTab: (t: Tab) => void}) {
  const M = useM();
  const st = useMemo(() => makeStyles(M), [M]);
  const items: [Tab, string, string][] = [
    ['dash', '▦', 'Dashboard'],
    ['devices', '▢', 'Devices'],
    ['files', '⎙', 'Files'],
    ['alerts', '◔', 'Alerts'],
  ];
  return (
    <View style={[st.tabbar, {paddingBottom: Math.max(M.insets.bottom, M.s(10))}]}>
      <View style={st.tabInner}>
        {items.map(([key, icon, label]) => {
          const on = tab === key;
          return (
            <Pressable key={key} style={st.tabItem} onPress={() => setTab(key)}>
              <Text style={[st.tabIcon, {color: on ? C.accent : C.faint}]}>{icon}</Text>
              <Text style={[st.tabLabel, {color: on ? C.accent : C.faint}]}>{label}</Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

/* ---------------- Dynamic styles (rebuilt when viewport changes) ---------------- */
function makeStyles(M: Metrics) {
  return StyleSheet.create({
    root: {flex: 1, backgroundColor: C.bg},
    scroll: {paddingHorizontal: M.pad, paddingBottom: M.s(24), paddingTop: M.s(2), alignItems: 'center'},
    column: {width: '100%', maxWidth: M.contentMax, gap: M.gap},
    cardHead: {flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between'},
    cardTitle: {color: C.text, fontSize: M.f(17), fontWeight: '700'},
    section: {color: C.sub, fontSize: M.f(12), fontWeight: '700', letterSpacing: 0.5, marginTop: 4},
    empty: {color: C.faint, fontSize: M.f(13), paddingVertical: M.s(8)},
    rowTitle: {color: C.text, fontSize: M.f(14), fontWeight: '600'},
    rowSub: {color: C.sub, fontSize: M.f(12), marginTop: 2},
    chev: {color: C.faint, fontSize: M.f(20)},
    divider: {height: 1, backgroundColor: C.border},
    // preview
    preview: {
      backgroundColor: '#070811',
      borderRadius: R.md,
      borderWidth: 1,
      borderColor: C.border,
      height: M.previewH,
      alignItems: 'center',
      justifyContent: 'center',
      marginTop: M.s(12),
    },
    previewBig: {fontSize: M.f(54), color: C.accent},
    previewText: {color: C.sub, marginTop: 10, fontSize: M.f(13), textAlign: 'center', paddingHorizontal: 16},
    toolRow: {flexDirection: 'row', gap: 10, marginTop: M.s(14)},
    tool: {
      flex: 1,
      backgroundColor: C.cardSoft,
      borderWidth: 1,
      borderColor: C.border,
      borderRadius: R.md,
      paddingVertical: M.s(12),
      alignItems: 'center',
      gap: 4,
    },
    toolLabel: {color: C.sub, fontSize: M.f(11)},
    metricRow: {flexDirection: 'row', marginVertical: M.s(14), paddingHorizontal: 4},
    metricLabel: {color: C.faint, fontSize: M.f(10), fontWeight: '700', letterSpacing: 1},
    metricValue: {color: C.text, fontSize: M.f(18), fontWeight: '700', marginTop: 2},
    // devices
    deviceCard: {
      backgroundColor: C.cardSoft,
      borderRadius: R.md,
      borderWidth: 1,
      borderColor: C.border,
      padding: M.s(14),
      gap: M.s(14),
    },
    deviceTop: {flexDirection: 'row', alignItems: 'center'},
    deviceName: {color: C.text, fontSize: M.f(16), fontWeight: '700'},
    statRow: {flexDirection: 'row', gap: 10},
    refresh: {
      width: M.s(50),
      backgroundColor: C.cardSoft,
      borderRadius: R.md,
      borderWidth: 1,
      borderColor: C.border,
      alignItems: 'center',
      justifyContent: 'center',
    },
    addBtn: {
      borderWidth: 1,
      borderColor: C.border,
      borderStyle: 'dashed',
      borderRadius: R.md,
      paddingVertical: M.s(14),
      alignItems: 'center',
    },
    // files
    linkCard: {
      flexDirection: 'row',
      alignItems: 'center',
      backgroundColor: C.cardSoft,
      borderRadius: R.md,
      borderWidth: 1,
      borderColor: C.border,
      padding: M.s(14),
    },
    scanChip: {
      borderWidth: 1,
      borderColor: C.accent,
      borderRadius: 999,
      paddingHorizontal: 14,
      paddingVertical: 7,
    },
    sendBox: {
      backgroundColor: C.accentSoft,
      borderRadius: R.md,
      borderWidth: 1,
      borderColor: C.accentDim,
      paddingVertical: M.s(26),
      alignItems: 'center',
    },
    track: {height: 5, backgroundColor: C.border, borderRadius: 3, marginTop: -2, marginBottom: 6, overflow: 'hidden'},
    fill: {height: 5, backgroundColor: C.accent, borderRadius: 3},
    // alerts
    alertBox: {
      backgroundColor: C.cardSoft,
      borderRadius: R.md,
      borderWidth: 1,
      borderColor: C.border,
      padding: M.s(14),
    },
    // tabbar
    tabbar: {
      backgroundColor: C.bgElev,
      borderTopWidth: 1,
      borderTopColor: C.border,
      paddingTop: M.s(8),
      alignItems: 'center',
    },
    tabInner: {flexDirection: 'row', width: '100%', maxWidth: M.contentMax},
    tabItem: {flex: 1, alignItems: 'center', gap: 3},
    tabIcon: {fontSize: M.f(20)},
    tabLabel: {fontSize: M.f(11), fontWeight: '600'},
    // scanner
    scanRoot: {flex: 1, backgroundColor: '#000'},
    scanLoading: {alignItems: 'center', justifyContent: 'center', backgroundColor: '#000'},
    // manual-connect modal
    modalWrap: {
      flex: 1,
      backgroundColor: 'rgba(0,0,0,0.6)',
      alignItems: 'center',
      justifyContent: 'center',
      padding: 24,
    },
    modalCard: {
      width: '100%',
      maxWidth: 380,
      backgroundColor: C.card,
      borderWidth: 1,
      borderColor: C.border,
      borderRadius: R.lg,
      padding: M.s(18),
      gap: M.s(12),
    },
    input: {
      backgroundColor: C.cardSoft,
      borderWidth: 1,
      borderColor: C.border,
      borderRadius: R.md,
      paddingHorizontal: 14,
      paddingVertical: 12,
      color: C.text,
      fontSize: M.f(15),
    },
    scanOverlay: {
      position: 'absolute',
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      alignItems: 'center',
      justifyContent: 'center',
    },
    reticle: {width: M.s(240), height: M.s(240), borderWidth: 3, borderColor: C.accent, borderRadius: 24},
    scanHint: {color: '#fff', fontSize: M.f(16), marginTop: 24},
    cancel: {
      position: 'absolute',
      alignSelf: 'center',
      backgroundColor: C.card,
      paddingHorizontal: 32,
      paddingVertical: 14,
      borderRadius: 12,
    },
  });
}
