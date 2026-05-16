// App shell — UNIFIED layout. Widget stays the same size in every state; transcript and history are always visible.
// Window: 560x680. Layout: header / capture-zone / transcript / history.

const { useState: useState_a, useEffect: useEffect_a } = React;

function useTweaks() {
  const [t, setT] = useState_a(window.__TWEAKS);
  useEffect_a(() => {
    const handler = (e) => {
      if (e.data && e.data.type === '__activate_edit_mode') setShowTweaks(true);
      if (e.data && e.data.type === '__deactivate_edit_mode') setShowTweaks(false);
    };
    window.addEventListener('message', handler);
    window.parent && window.parent.postMessage({ type: '__edit_mode_available' }, '*');
    return () => window.removeEventListener('message', handler);
  }, []);
  const [showTweaks, setShowTweaks] = useState_a(false);
  return [t, setT, showTweaks, setShowTweaks];
}

const ACCENT_MAP = { cyan: '#7be4ff', amber: '#ffb340', green: '#6bffb3', violet: '#c7a8ff' };

function App() {
  const [tweaks, setTweaks, showTweaks, setShowTweaks] = useTweaks();
  const settingsOpen = !!tweaks.showSettings;
  const setSettingsOpen = (v) => {
    setTweaks({ ...tweaks, showSettings: v });
    window.parent && window.parent.postMessage({ type: '__edit_mode_set_keys', edits: { showSettings: v } }, '*');
  };

  const stateColor = tweaks.state === 'rec' ? '#ff4757'
                  : tweaks.state === 'decoding' ? '#ffb340'
                  : (ACCENT_MAP[tweaks.accent] || '#7be4ff');

  // simulated elapsed
  const [elapsed, setElapsed] = useState_a(0);
  useEffect_a(() => {
    if (tweaks.state === 'idle') { setElapsed(0); return; }
    if (tweaks.state === 'decoding') { setElapsed(34.7); return; }
    const id = setInterval(() => setElapsed(e => e + 0.1), 100);
    return () => clearInterval(id);
  }, [tweaks.state]);

  const mm = String(Math.floor(elapsed / 60)).padStart(2, '0');
  const ss = String(Math.floor(elapsed % 60)).padStart(2, '0');
  const ds = String(Math.floor((elapsed * 10) % 10));
  const elapsedStr = `${mm}:${ss}.${ds}`;

  const stateLabel = tweaks.state === 'rec' ? 'REC' : tweaks.state === 'decoding' ? 'DECODE' : 'IDLE';
  const accentCol = ACCENT_MAP[tweaks.accent] || '#7be4ff';
  const ctaText = tweaks.state === 'rec' ? 'TO STOP & TRANSCRIBE'
                : tweaks.state === 'decoding' ? 'TO CANCEL DECODING'
                : 'TO START DICTATION';

  return (
    <div style={{
      width: '100%', height: '100%',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'radial-gradient(ellipse at center, #0a0f1e 0%, #03040a 60%, #000 100%)',
      position: 'relative', overflow: 'hidden',
    }}>
      <BackgroundGrid show={tweaks.showGrid} />

      <div style={{
        width: 560, height: 680,
        background: 'var(--surface-1)',
        position: 'relative',
        boxShadow: `
          0 0 0 1px rgba(138,149,172,0.18),
          0 0 0 6px rgba(138,149,172,0.03),
          0 30px 80px rgba(0,0,0,0.65),
          0 0 70px ${stateColor}33
        `,
        transition: 'box-shadow 320ms ease',
        display: 'flex', flexDirection: 'column',
      }}>
        <CornerBrackets color={stateColor} />

        <Header
          state={tweaks.state}
          accent={tweaks.accent}
          hotkey="F9"
          showWaveStrip={tweaks.showWaveStrip}
          onSettings={() => setSettingsOpen(true)}
          onMin={() => {}}
          onClose={() => {}}
        />

        {/* ── Capture zone: widget always 200px, meta on right ── */}
        <div style={{
          padding: '12px 18px 8px 18px',
          display: 'grid',
          gridTemplateColumns: '200px 1fr',
          columnGap: 18,
          alignItems: 'center',
          borderBottom: '1px solid rgba(138,149,172,0.12)',
          background: `linear-gradient(180deg, color-mix(in oklab, ${stateColor} 5%, transparent) 0%, transparent 100%)`,
        }}>
          <RecordWidget state={tweaks.state} accent={tweaks.accent} ringDensity={tweaks.ringDensity} size={200} />

          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <StatRow label="STATE" value={stateLabel} valueColor={stateColor} big highlight={tweaks.state !== 'idle'} />
            <Divider />
            <StatRow label="ELAPSED" value={elapsedStr} mono active={tweaks.state === 'rec'} accent={tweaks.accent} />
            <StatRow label="PEAK" value={tweaks.state === 'rec' ? '-3.2 dB' : tweaks.state === 'decoding' ? '-6.1 dB' : '-∞ dB'} mono dim />
            <Divider />
            <LevelRow state={tweaks.state} accent={tweaks.accent} />
          </div>
        </div>

        {/* ── CTA bar ── */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          gap: 10, padding: '7px 16px',
          borderBottom: '1px solid rgba(138,149,172,0.10)',
        }}>
          <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 10, color: 'var(--text-dim)', letterSpacing: '0.14em' }}>PRESS</span>
          <span style={{
            fontFamily: 'JetBrains Mono, monospace', fontWeight: 600, fontSize: 11, color: 'var(--text-hi)',
            padding: '3px 10px',
            border: `1px solid ${tweaks.state === 'idle' ? 'rgba(138,149,172,0.35)' : stateColor}`,
            background: tweaks.state === 'idle' ? 'transparent' : `color-mix(in oklab, ${stateColor} 12%, transparent)`,
            letterSpacing: '0.16em',
            clipPath: 'polygon(6px 0, 100% 0, 100% calc(100% - 6px), calc(100% - 6px) 100%, 0 100%, 0 6px)',
          }}>F9</span>
          <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 10, color: 'var(--text-dim)', letterSpacing: '0.14em' }}>{ctaText}</span>
        </div>

        {/* ── Transcript (always visible) ── */}
        <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0, padding: '10px 0 0 0' }}>
          <TranscriptView state={tweaks.state} length={tweaks.transcriptLen || 'medium'} accent={tweaks.accent} />
        </div>

        {/* ── History (compact) ── */}
        <CompactHistory accent={tweaks.accent} />

        {settingsOpen && <Settings onClose={() => setSettingsOpen(false)} accent={tweaks.accent} />}
      </div>

      {showTweaks && <Tweaks tweaks={tweaks} onChange={setTweaks} />}

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes pulseDot {
          0%, 100% { box-shadow: 0 0 4px currentColor; opacity: 1; }
          50%      { box-shadow: 0 0 10px currentColor; opacity: 0.6; }
        }
        @keyframes pulseRing {
          0%, 100% { transform: scale(1); opacity: 0.4; }
          50% { transform: scale(1.1); opacity: 0.8; }
        }
        @keyframes caretBlink {
          0%, 50% { opacity: 1; }
          50.01%, 100% { opacity: 0; }
        }
        @keyframes txDot {
          0%, 100% { opacity: 0.25; transform: scale(0.8); }
          50% { opacity: 1; transform: scale(1.1); }
        }
        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-thumb { background: rgba(138,149,172,0.25); }
        ::-webkit-scrollbar-thumb:hover { background: rgba(138,149,172,0.4); }
        ::-webkit-scrollbar-track { background: transparent; }
        .transcript-scroll::-webkit-scrollbar { width: 8px; }
        .transcript-scroll::-webkit-scrollbar-thumb { background: rgba(138,149,172,0.35); border-radius: 0; }
        .transcript-scroll::-webkit-scrollbar-thumb:hover { background: rgba(138,149,172,0.55); }
      `}</style>
    </div>
  );
}

function StatRow({ label, value, mono, big, highlight, active, dim, valueColor, accent }) {
  const accentCol = accent ? ACCENT_MAP[accent] : null;
  const color = valueColor || (highlight ? valueColor : active ? accentCol : dim ? 'var(--text-mid)' : 'var(--text-hi)');
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '56px 1fr', columnGap: 10, alignItems: 'baseline' }}>
      <span style={{
        fontFamily: 'JetBrains Mono, monospace', fontSize: 8,
        color: 'var(--text-dim)', letterSpacing: '0.18em',
      }}>{label}</span>
      <span style={{
        fontFamily: mono ? 'JetBrains Mono, monospace' : 'Rajdhani, sans-serif',
        fontWeight: big ? 700 : mono ? 500 : 600,
        fontSize: big ? 20 : mono ? 14 : 13,
        letterSpacing: mono ? '0.04em' : big ? '0.22em' : '0.14em',
        fontVariantNumeric: 'tabular-nums',
        color,
        textShadow: highlight ? `0 0 8px ${valueColor || color}55` : 'none',
        whiteSpace: 'nowrap',
        lineHeight: 1,
      }}>{value}</span>
    </div>
  );
}

function Divider() {
  return <div style={{ height: 1, background: 'linear-gradient(90deg, rgba(138,149,172,0.18), transparent 80%)' }} />;
}

function LevelRow({ state, accent }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '56px 1fr', columnGap: 10, alignItems: 'center' }}>
      <span style={{
        fontFamily: 'JetBrains Mono, monospace', fontSize: 8,
        color: 'var(--text-dim)', letterSpacing: '0.18em',
      }}>LEVEL</span>
      <LevelMeter state={state} accent={accent} width={140} />
    </div>
  );
}

function CornerBrackets({ color }) {
  const sz = 12, off = -1;
  const corner = (rot, pos) => (
    <svg width={sz} height={sz} viewBox="0 0 12 12" style={{ position: 'absolute', ...pos, transform: `rotate(${rot}deg)`, pointerEvents: 'none' }}>
      <polyline points="0,5 0,0 5,0" stroke={color} strokeWidth="1.5" fill="none" />
    </svg>
  );
  return <>
    {corner(0,   { top: off, left: off })}
    {corner(90,  { top: off, right: off })}
    {corner(180, { bottom: off, right: off })}
    {corner(270, { bottom: off, left: off })}
  </>;
}

function BackgroundGrid({ show }) {
  if (!show) return null;
  return (
    <div style={{
      position: 'absolute', inset: 0,
      backgroundImage: `
        linear-gradient(rgba(123,228,255,0.04) 1px, transparent 1px),
        linear-gradient(90deg, rgba(123,228,255,0.04) 1px, transparent 1px)
      `,
      backgroundSize: '32px 32px',
      pointerEvents: 'none',
    }}/>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
