// Header: wordmark, hotkey, status pill, divider, optional waveform mini-strip
const { useEffect: useEffect_h, useRef: useRef_h } = React;

function StatusPill({ state, accent }) {
  const label = state === 'rec' ? 'REC' : state === 'decoding' ? 'DECODING' : 'READY';
  const col = state === 'rec' ? 'var(--crimson)' : state === 'decoding' ? 'var(--amber)' : `var(--${accent === 'cyan' ? 'cyan' : accent})`;
  return (
    <div style={{
      display: 'inline-flex', alignItems: 'center', gap: 8,
      padding: '4px 10px 4px 8px',
      border: `1px solid ${state === 'idle' ? 'rgba(138,149,172,0.28)' : col}`,
      background: state === 'idle' ? 'transparent' : `color-mix(in oklab, ${col} 10%, transparent)`,
      fontFamily: 'Rajdhani, sans-serif',
      fontWeight: 600,
      fontSize: 11,
      letterSpacing: '0.18em',
      color: state === 'idle' ? 'var(--text-mid)' : col,
      clipPath: 'polygon(8px 0, 100% 0, 100% calc(100% - 8px), calc(100% - 0px) 100%, 0 100%, 0 8px)',
      height: 22,
    }}>
      {state === 'rec' ? (
        <span style={{
          width: 8, height: 8, borderRadius: '50%', background: col,
          boxShadow: `0 0 6px ${col}`,
          animation: 'pulseDot 1.2s ease-in-out infinite'
        }} />
      ) : state === 'decoding' ? (
        <span style={{
          width: 8, height: 8, borderRadius: '50%',
          border: `1.5px solid ${col}`, borderTopColor: 'transparent',
          animation: 'spin 0.9s linear infinite'
        }} />
      ) : (
        <span style={{ width: 8, height: 8, border: `1px solid ${col}`, transform: 'rotate(45deg)' }} />
      )}
      <span>{label}</span>
    </div>
  );
}

function WaveStrip({ state }) {
  const ref = useRef_h(null);
  useEffect_h(() => {
    const c = ref.current; if (!c) return;
    const ctx = c.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const w = 120, h = 22;
    c.width = w * dpr; c.height = h * dpr;
    c.style.width = w + 'px'; c.style.height = h + 'px';
    ctx.scale(dpr, dpr);
    // generate a fake recent waveform
    const bars = 36;
    const samples = [];
    for (let i = 0; i < bars; i++) {
      const age = i / bars;
      const env = state === 'rec' ? (0.3 + Math.abs(Math.sin(i * 0.9)) * 0.7) : (0.2 + Math.abs(Math.sin(i * 0.7)) * 0.5 * age);
      samples.push(env);
    }
    ctx.clearRect(0, 0, w, h);
    const col = state === 'rec' ? '#ff4757' : 'rgba(123,228,255,0.55)';
    const dim = 'rgba(138,149,172,0.2)';
    for (let i = 0; i < bars; i++) {
      const bh = Math.max(1, samples[i] * (h - 2));
      const x = i * (w / bars);
      ctx.fillStyle = i > bars - 6 ? col : dim;
      ctx.fillRect(x + 0.5, (h - bh) / 2, 2, bh);
    }
  }, [state]);
  return <canvas ref={ref} style={{ display: 'block' }} />;
}

function Header({ state, accent, hotkey, showWaveStrip, onSettings, onMin, onClose }) {
  const dotCol = state === 'rec' ? 'var(--crimson)' : state === 'decoding' ? 'var(--amber)' : `var(--${accent})`;
  return (
    <div style={{
      display: 'flex', alignItems: 'center',
      padding: '12px 16px 10px 16px',
      gap: 12,
      WebkitAppRegion: 'drag',
      position: 'relative',
    }}>
      {/* Brand mark */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <svg width="18" height="18" viewBox="0 0 18 18" style={{ display: 'block' }}>
          <circle cx="9" cy="9" r="7.5" fill="none" stroke="rgba(138,149,172,0.4)" strokeWidth="1" />
          <circle cx="9" cy="9" r="3" fill={dotCol} />
          <circle cx="9" cy="9" r="5" fill="none" stroke={dotCol} strokeWidth="1" opacity="0.5" />
        </svg>
        <div style={{
          fontFamily: 'Rajdhani, sans-serif', fontWeight: 700,
          fontSize: 18, letterSpacing: '0.32em', color: 'var(--text-hi)',
        }}>DICT</div>
      </div>

      {/* hotkey slab */}
      <div style={{
        display: 'inline-flex', alignItems: 'center', gap: 6,
        padding: '3px 8px',
        border: '1px solid rgba(138,149,172,0.28)',
        fontFamily: 'JetBrains Mono, monospace', fontSize: 10,
        letterSpacing: '0.1em', color: 'var(--text-mid)',
        clipPath: 'polygon(6px 0, 100% 0, 100% calc(100% - 6px), calc(100% - 6px) 100%, 0 100%, 0 6px)',
      }}>
        <span style={{ color: 'var(--text-dim)' }}>HOTKEY</span>
        <span style={{ color: 'var(--text-hi)' }}>{hotkey}</span>
      </div>

      <StatusPill state={state} accent={accent} />

      {showWaveStrip && (
        <div style={{ marginLeft: 'auto', marginRight: 8, opacity: 0.9 }}>
          <WaveStrip state={state} />
        </div>
      )}

      {/* Window controls */}
      <div style={{
        display: 'flex', gap: 2, marginLeft: showWaveStrip ? 0 : 'auto',
        WebkitAppRegion: 'no-drag',
      }}>
        <WinBtn onClick={onSettings} title="Settings">
          <svg width="14" height="14" viewBox="0 0 14 14">
            <circle cx="7" cy="7" r="2.2" fill="none" stroke="currentColor" strokeWidth="1.2"/>
            {[0,45,90,135,180,225,270,315].map(a => (
              <line key={a} x1="7" y1="1.5" x2="7" y2="3.2" stroke="currentColor" strokeWidth="1.2" transform={`rotate(${a} 7 7)`}/>
            ))}
          </svg>
        </WinBtn>
        <WinBtn onClick={onMin} title="Minimize">
          <svg width="14" height="14" viewBox="0 0 14 14"><line x1="3" y1="10" x2="11" y2="10" stroke="currentColor" strokeWidth="1.2"/></svg>
        </WinBtn>
        <WinBtn onClick={onClose} title="Close" danger>
          <svg width="14" height="14" viewBox="0 0 14 14"><line x1="3.5" y1="3.5" x2="10.5" y2="10.5" stroke="currentColor" strokeWidth="1.2"/><line x1="10.5" y1="3.5" x2="3.5" y2="10.5" stroke="currentColor" strokeWidth="1.2"/></svg>
        </WinBtn>
      </div>

      {/* divider line absolute */}
      <div style={{
        position: 'absolute', left: 16, right: 16, bottom: 0, height: 1,
        background: 'linear-gradient(90deg, transparent 0%, rgba(138,149,172,0.35) 10%, rgba(138,149,172,0.35) 90%, transparent 100%)'
      }} />
    </div>
  );
}

function WinBtn({ children, onClick, title, danger }) {
  const [hover, setHover] = React.useState(false);
  return (
    <button
      onClick={onClick}
      title={title}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        width: 28, height: 24,
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        background: hover ? (danger ? 'rgba(255,71,87,0.15)' : 'rgba(138,149,172,0.12)') : 'transparent',
        border: 'none', cursor: 'pointer',
        color: hover ? (danger ? '#ff4757' : 'var(--text-hi)') : 'var(--text-mid)',
        transition: 'all 120ms ease',
      }}
    >
      {children}
    </button>
  );
}

window.Header = Header;
window.StatusPill = StatusPill;
