// Tweaks panel — design-time controls surfaced via toolbar toggle.
const { useState: useState_t, useEffect: useEffect_t } = React;

function Tweaks({ tweaks, onChange }) {
  const set = (k, v) => {
    const next = { ...tweaks, [k]: v };
    onChange(next);
    if (window.parent !== window) {
      window.parent.postMessage({ type: '__edit_mode_set_keys', edits: { [k]: v } }, '*');
    }
  };
  const row = { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 };
  const label = { fontFamily: 'Rajdhani, sans-serif', fontWeight: 600, fontSize: 10, letterSpacing: '0.2em', color: '#8a95ac', width: 82 };
  const chipRow = { display: 'flex', gap: 4, flex: 1 };
  const chip = (active) => ({
    padding: '3px 8px',
    fontFamily: 'JetBrains Mono, monospace', fontSize: 10,
    border: `1px solid ${active ? '#7be4ff' : 'rgba(138,149,172,0.22)'}`,
    color: active ? '#7be4ff' : '#8a95ac',
    background: active ? 'rgba(123,228,255,0.08)' : 'transparent',
    cursor: 'pointer',
  });
  return (
    <div style={{
      position: 'fixed', bottom: 20, right: 20,
      width: 260,
      background: 'rgba(10,14,26,0.96)',
      border: '1px solid rgba(138,149,172,0.3)',
      padding: 14,
      fontFamily: 'Rajdhani, sans-serif',
      zIndex: 1000,
      boxShadow: '0 16px 40px rgba(0,0,0,0.6)',
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        paddingBottom: 10, marginBottom: 12,
        borderBottom: '1px solid rgba(138,149,172,0.2)',
      }}>
        <span style={{ width: 6, height: 6, background: '#7be4ff' }} />
        <span style={{ fontWeight: 700, fontSize: 11, letterSpacing: '0.28em', color: '#e6edf7' }}>TWEAKS</span>
      </div>

      <div style={row}>
        <span style={label}>STATE</span>
        <div style={chipRow}>
          {['idle','rec','decoding'].map(s => (
            <button key={s} style={chip(tweaks.state === s)} onClick={() => set('state', s)}>{s.toUpperCase()}</button>
          ))}
        </div>
      </div>

      <div style={row}>
        <span style={label}>ACCENT</span>
        <div style={chipRow}>
          {['cyan','amber','green','violet'].map(a => (
            <button key={a} style={{ ...chip(tweaks.accent === a), padding: 0, width: 18, height: 18, position: 'relative' }} onClick={() => set('accent', a)}>
              <span style={{
                position: 'absolute', inset: 3,
                background: { cyan: '#7be4ff', amber: '#ffb340', green: '#6bffb3', violet: '#c7a8ff' }[a],
              }} />
            </button>
          ))}
        </div>
      </div>

      <div style={row}>
        <span style={label}>RING</span>
        <div style={chipRow}>
          {[54,72,96].map(n => (
            <button key={n} style={chip(tweaks.ringDensity === n)} onClick={() => set('ringDensity', n)}>{n}</button>
          ))}
        </div>
      </div>

      <div style={row}>
        <span style={label}>WAVE STRIP</span>
        <div style={chipRow}>
          {[true,false].map(v => (
            <button key={String(v)} style={chip(tweaks.showWaveStrip === v)} onClick={() => set('showWaveStrip', v)}>{v ? 'ON' : 'OFF'}</button>
          ))}
        </div>
      </div>

      <div style={row}>
        <span style={label}>TRANSCRIPT</span>
        <div style={chipRow}>
          {['empty','short','medium','long'].map(v => (
            <button key={v} style={chip(tweaks.transcriptLen === v)} onClick={() => set('transcriptLen', v)}>{v.toUpperCase()}</button>
          ))}
        </div>
      </div>

      <div style={row}>
        <span style={label}>SETTINGS</span>
        <div style={chipRow}>
          {[true,false].map(v => (
            <button key={String(v)} style={chip(tweaks.showSettings === v)} onClick={() => set('showSettings', v)}>{v ? 'OPEN' : 'CLOSED'}</button>
          ))}
        </div>
      </div>

      <div style={{ ...row, marginBottom: 0 }}>
        <span style={label}>4PX GRID</span>
        <div style={chipRow}>
          {[true,false].map(v => (
            <button key={String(v)} style={chip(tweaks.showGrid === v)} onClick={() => set('showGrid', v)}>{v ? 'SHOW' : 'HIDE'}</button>
          ))}
        </div>
      </div>
    </div>
  );
}

window.Tweaks = Tweaks;
