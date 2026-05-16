// Settings dialog — grouped sections on 4px grid, shares record-widget palette.
// Sections: AUDIO / HOTKEY / APPEARANCE. New: MIC GAIN log slider (0.5×–5×).
const { useState: useState_s, useRef: useRef_s, useEffect: useEffect_s } = React;

function SectionTitle({ label, num }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'baseline', gap: 10,
      padding: '0 0 8px 0',
      borderBottom: '1px solid rgba(138,149,172,0.18)',
      marginBottom: 16,
    }}>
      <span style={{
        fontFamily: 'JetBrains Mono, monospace', fontSize: 9,
        color: 'var(--text-dim)', letterSpacing: '0.1em',
      }}>§{num}</span>
      <span style={{
        fontFamily: 'Rajdhani, sans-serif', fontWeight: 600, fontSize: 12,
        letterSpacing: '0.24em', color: 'var(--text-hi)',
      }}>{label}</span>
      <span style={{ flex: 1, height: 1, background: 'linear-gradient(90deg, rgba(138,149,172,0.25), transparent)' }} />
    </div>
  );
}

function Field({ label, children, hint }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '96px 1fr', columnGap: 12, alignItems: 'center', minHeight: 28, marginBottom: 8 }}>
      <label style={{
        fontFamily: 'Rajdhani, sans-serif', fontSize: 11, fontWeight: 500,
        letterSpacing: '0.14em', color: 'var(--text-mid)',
        textTransform: 'uppercase',
      }}>{label}</label>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        {children}
        {hint && <span style={{
          fontFamily: 'JetBrains Mono, monospace', fontSize: 9,
          color: 'var(--text-dim)', letterSpacing: '0.06em', marginLeft: 'auto',
        }}>{hint}</span>}
      </div>
    </div>
  );
}

function Select({ value, options, onChange, accent }) {
  const [open, setOpen] = useState_s(false);
  return (
    <div style={{ position: 'relative', flex: 1 }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          width: '100%', height: 24,
          padding: '0 10px',
          background: 'rgba(138,149,172,0.06)',
          border: '1px solid rgba(138,149,172,0.22)',
          color: 'var(--text-hi)',
          fontFamily: 'JetBrains Mono, monospace', fontSize: 11,
          letterSpacing: '0.04em',
          textAlign: 'left',
          cursor: 'pointer',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        }}>
        <span>{value}</span>
        <span style={{ color: `var(--${accent})`, fontSize: 9 }}>▼</span>
      </button>
      {open && (
        <div style={{
          position: 'absolute', top: '100%', left: 0, right: 0,
          background: 'var(--surface-2)',
          border: '1px solid rgba(138,149,172,0.28)',
          borderTop: 'none',
          zIndex: 10,
        }}>
          {options.map(opt => (
            <div
              key={opt}
              onClick={() => { onChange(opt); setOpen(false); }}
              style={{
                padding: '5px 10px',
                fontFamily: 'JetBrains Mono, monospace', fontSize: 11,
                color: opt === value ? `var(--${accent})` : 'var(--text-mid)',
                cursor: 'pointer',
                borderLeft: opt === value ? `2px solid var(--${accent})` : '2px solid transparent',
              }}
              onMouseEnter={e => e.currentTarget.style.background = 'rgba(138,149,172,0.08)'}
              onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
            >
              {opt}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function HotkeyInput({ value, accent }) {
  return (
    <div style={{
      display: 'inline-flex', gap: 4, padding: '3px 8px',
      border: '1px solid rgba(138,149,172,0.28)',
      background: 'rgba(138,149,172,0.04)',
      fontFamily: 'JetBrains Mono, monospace', fontSize: 11,
      color: 'var(--text-hi)', letterSpacing: '0.08em',
      minWidth: 80,
    }}>
      <span style={{ color: 'var(--text-dim)' }}>›</span>
      <span>{value}</span>
      <span style={{ marginLeft: 'auto', color: `var(--${accent})`, fontSize: 9, alignSelf: 'center' }}>REBIND</span>
    </div>
  );
}

function LinearSlider({ value, min, max, step, onChange, accent, format }) {
  const ref = useRef_s(null);
  const [dragging, setDragging] = useState_s(false);
  const pct = (value - min) / (max - min);

  const handle = (e) => {
    const r = ref.current.getBoundingClientRect();
    const p = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
    let v = min + p * (max - min);
    if (step) v = Math.round(v / step) * step;
    onChange(v);
  };

  useEffect_s(() => {
    if (!dragging) return;
    const m = (e) => handle(e);
    const u = () => setDragging(false);
    window.addEventListener('mousemove', m);
    window.addEventListener('mouseup', u);
    return () => { window.removeEventListener('mousemove', m); window.removeEventListener('mouseup', u); };
  });

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, flex: 1 }}>
      <div
        ref={ref}
        onMouseDown={(e) => { setDragging(true); handle(e); }}
        style={{
          flex: 1, height: 20, position: 'relative', cursor: 'pointer',
          display: 'flex', alignItems: 'center',
        }}>
        {/* track */}
        <div style={{
          position: 'absolute', left: 0, right: 0, top: '50%', transform: 'translateY(-50%)',
          height: 2, background: 'rgba(138,149,172,0.18)',
        }} />
        {/* tick marks */}
        {[0, 0.25, 0.5, 0.75, 1].map(t => (
          <div key={t} style={{
            position: 'absolute', left: `${t * 100}%`, top: '50%',
            width: 1, height: 6, transform: 'translate(-50%, -50%)',
            background: 'rgba(138,149,172,0.28)',
          }} />
        ))}
        {/* fill */}
        <div style={{
          position: 'absolute', left: 0, top: '50%', transform: 'translateY(-50%)',
          width: `${pct * 100}%`, height: 2,
          background: `var(--${accent})`,
          boxShadow: `0 0 6px color-mix(in oklab, var(--${accent}) 60%, transparent)`,
        }} />
        {/* thumb */}
        <div style={{
          position: 'absolute', left: `${pct * 100}%`, top: '50%',
          transform: 'translate(-50%, -50%)',
          width: 10, height: 14,
          background: 'var(--surface-0)',
          border: `1px solid var(--${accent})`,
        }} />
      </div>
      <span style={{
        fontFamily: 'JetBrains Mono, monospace', fontSize: 10,
        color: 'var(--text-hi)', letterSpacing: '0.04em',
        fontVariantNumeric: 'tabular-nums', minWidth: 44, textAlign: 'right',
      }}>{format ? format(value) : value.toFixed(2)}</span>
    </div>
  );
}

// Log-scale gain slider 0.5×–5× with tick-callouts at 1× default and 3× (soft clip warning)
function GainSlider({ value, onChange, accent, livePreview }) {
  const ref = useRef_s(null);
  const [dragging, setDragging] = useState_s(false);
  const MIN = 0.5, MAX = 5;
  const LMIN = Math.log(MIN), LMAX = Math.log(MAX);
  const pct = (Math.log(value) - LMIN) / (LMAX - LMIN);
  const pct1x = (Math.log(1) - LMIN) / (LMAX - LMIN);
  const pct3x = (Math.log(3) - LMIN) / (LMAX - LMIN);

  const handle = (e) => {
    const r = ref.current.getBoundingClientRect();
    const p = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
    const v = Math.exp(LMIN + p * (LMAX - LMIN));
    onChange(Math.round(v * 20) / 20);
  };
  useEffect_s(() => {
    if (!dragging) return;
    const m = (e) => handle(e);
    const u = () => setDragging(false);
    window.addEventListener('mousemove', m);
    window.addEventListener('mouseup', u);
    return () => { window.removeEventListener('mousemove', m); window.removeEventListener('mouseup', u); };
  });
  const inHot = value > 3;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: 1 }}>
      <div
        ref={ref}
        onMouseDown={(e) => { setDragging(true); handle(e); }}
        style={{ position: 'relative', height: 22, cursor: 'pointer', display: 'flex', alignItems: 'center' }}
      >
        {/* track */}
        <div style={{ position: 'absolute', left: 0, right: 0, top: '50%', transform: 'translateY(-50%)', height: 2, background: 'rgba(138,149,172,0.18)' }} />
        {/* safe zone fill up to 3x */}
        <div style={{
          position: 'absolute', left: 0, top: '50%', transform: 'translateY(-50%)',
          width: `${Math.min(pct, pct3x) * 100}%`, height: 2, background: `var(--${accent})`,
        }} />
        {/* hot zone fill (red) */}
        {inHot && (
          <div style={{
            position: 'absolute', left: `${pct3x * 100}%`, top: '50%', transform: 'translateY(-50%)',
            width: `${(pct - pct3x) * 100}%`, height: 2, background: 'var(--crimson)',
          }} />
        )}
        {/* default 1× marker */}
        <div style={{
          position: 'absolute', left: `${pct1x * 100}%`, top: 0, bottom: 0,
          width: 1, background: 'rgba(205,215,235,0.35)',
        }} />
        <div style={{
          position: 'absolute', left: `${pct1x * 100}%`, bottom: -10,
          transform: 'translateX(-50%)',
          fontFamily: 'JetBrains Mono, monospace', fontSize: 8,
          color: 'var(--text-dim)', letterSpacing: '0.06em',
        }}>1×</div>
        {/* 3× hot marker */}
        <div style={{
          position: 'absolute', left: `${pct3x * 100}%`, top: 0, bottom: 0,
          width: 1, background: 'rgba(255,71,87,0.4)',
        }} />
        <div style={{
          position: 'absolute', left: `${pct3x * 100}%`, bottom: -10,
          transform: 'translateX(-50%)',
          fontFamily: 'JetBrains Mono, monospace', fontSize: 8,
          color: 'rgba(255,71,87,0.7)', letterSpacing: '0.06em',
        }}>CLIP</div>
        {/* thumb */}
        <div style={{
          position: 'absolute', left: `${pct * 100}%`, top: '50%',
          transform: 'translate(-50%, -50%)',
          width: 10, height: 14,
          background: 'var(--surface-0)',
          border: `1px solid ${inHot ? 'var(--crimson)' : `var(--${accent})`}`,
        }} />
      </div>
      {/* live preview row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, height: 14, paddingTop: 8 }}>
        <span style={{
          fontFamily: 'Rajdhani, sans-serif', fontSize: 9, letterSpacing: '0.18em',
          color: inHot ? 'var(--crimson)' : 'var(--text-dim)', fontWeight: 600,
        }}>{inHot ? 'HOT' : 'LIVE'}</span>
        <PreviewBars gain={value} accent={accent} inHot={inHot} />
        <span style={{
          fontFamily: 'JetBrains Mono, monospace', fontSize: 10,
          color: 'var(--text-hi)', fontVariantNumeric: 'tabular-nums',
          marginLeft: 'auto',
        }}>{value.toFixed(2)}×</span>
      </div>
    </div>
  );
}

function PreviewBars({ gain, accent, inHot }) {
  const ref = useRef_s(null);
  useEffect_s(() => {
    const c = ref.current; if (!c) return;
    const ctx = c.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const W = 140, H = 10;
    c.width = W * dpr; c.height = H * dpr;
    c.style.width = W + 'px'; c.style.height = H + 'px';
    ctx.scale(dpr, dpr);
    let raf;
    const draw = () => {
      ctx.clearRect(0, 0, W, H);
      const bars = 28;
      for (let i = 0; i < bars; i++) {
        const env = (Math.sin(performance.now() * 0.005 + i * 0.6) + 1) / 2;
        const amp = Math.min(1, env * 0.5 * gain);
        const barW = Math.floor((W - bars) / bars);
        const x = i * (barW + 1);
        const h = Math.max(1, amp * H);
        ctx.fillStyle = amp > 0.85 ? '#ff4757' : amp > 0.6 ? (inHot ? '#ff4757' : `var(--${accent})`) : 'rgba(138,149,172,0.45)';
        // fillStyle doesn't resolve var() — compute
        const accentMap = { cyan: '#7be4ff', amber: '#ffb340', green: '#6bffb3', violet: '#c7a8ff' };
        ctx.fillStyle = amp > 0.85 ? '#ff4757' : amp > 0.5 ? accentMap[accent] || '#7be4ff' : 'rgba(138,149,172,0.45)';
        ctx.fillRect(x, (H - h) / 2, barW, h);
      }
      raf = requestAnimationFrame(draw);
    };
    draw();
    return () => cancelAnimationFrame(raf);
  }, [gain, accent, inHot]);
  return <canvas ref={ref} />;
}

function Toggle({ on, onChange, accent }) {
  return (
    <button
      onClick={() => onChange(!on)}
      style={{
        width: 32, height: 16, padding: 1,
        background: on ? `color-mix(in oklab, var(--${accent}) 22%, transparent)` : 'rgba(138,149,172,0.12)',
        border: `1px solid ${on ? `var(--${accent})` : 'rgba(138,149,172,0.28)'}`,
        cursor: 'pointer', display: 'flex', alignItems: 'center',
        justifyContent: on ? 'flex-end' : 'flex-start',
        transition: 'all 140ms ease',
      }}>
      <span style={{
        width: 10, height: 10,
        background: on ? `var(--${accent})` : 'var(--text-dim)',
        transition: 'all 140ms ease',
      }} />
    </button>
  );
}

function Settings({ onClose, accent }) {
  const [gain, setGain] = useState_s(1.0);
  const [vol, setVol] = useState_s(0.72);
  const [device, setDevice] = useState_s('Realtek Audio (default)');
  const [model, setModel] = useState_s('large-v3');
  const [lang, setLang] = useState_s('auto');
  const [hotkey] = useState_s('F9');
  const [pushToTalk, setPushToTalk] = useState_s(false);

  return (
    <div style={{
      position: 'absolute', inset: 0,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'rgba(3,4,10,0.72)',
      backdropFilter: 'blur(2px)',
      zIndex: 50,
    }}>
      <div style={{
        width: 496, maxHeight: 620,
        background: 'var(--surface-1)',
        border: '1px solid rgba(138,149,172,0.3)',
        position: 'relative',
        boxShadow: `0 0 0 1px rgba(0,0,0,0.6), 0 20px 48px rgba(0,0,0,0.6)`,
      }}>
        {/* corner brackets */}
        {[['tl',0,0],['tr','auto',0],['br','auto','auto'],['bl',0,'auto']].map(([k, r, b], i) => (
          <svg key={k} width="10" height="10" viewBox="0 0 10 10" style={{
            position: 'absolute',
            top: i < 2 ? -1 : 'auto', bottom: i >= 2 ? -1 : 'auto',
            left: (i === 0 || i === 3) ? -1 : 'auto', right: (i === 1 || i === 2) ? -1 : 'auto',
            transform: `rotate(${i*90}deg)`,
          }}>
            <polyline points="0,4 0,0 4,0" stroke={`var(--${accent})`} strokeWidth="1.5" fill="none" />
          </svg>
        ))}

        {/* header */}
        <div style={{
          display: 'flex', alignItems: 'center',
          padding: '10px 16px', borderBottom: '1px solid rgba(138,149,172,0.18)',
          gap: 10,
        }}>
          <span style={{
            fontFamily: 'JetBrains Mono, monospace', fontSize: 9,
            color: 'var(--text-dim)', letterSpacing: '0.12em',
          }}>CFG/</span>
          <span style={{
            fontFamily: 'Rajdhani, sans-serif', fontWeight: 600, fontSize: 13,
            letterSpacing: '0.28em', color: 'var(--text-hi)',
          }}>SETTINGS</span>
          <span style={{ marginLeft: 'auto' }}>
            <button onClick={onClose} style={{
              background: 'transparent', border: 'none', cursor: 'pointer',
              color: 'var(--text-mid)', width: 24, height: 20,
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            }}>
              <svg width="12" height="12" viewBox="0 0 12 12">
                <line x1="3" y1="3" x2="9" y2="9" stroke="currentColor" strokeWidth="1.2"/>
                <line x1="9" y1="3" x2="3" y2="9" stroke="currentColor" strokeWidth="1.2"/>
              </svg>
            </button>
          </span>
        </div>

        <div style={{ padding: '16px 20px', maxHeight: 540, overflow: 'auto' }}>
          {/* AUDIO */}
          <SectionTitle label="AUDIO" num="01" />
          <Field label="Input"><Select value={device} options={['Realtek Audio (default)','Shure MV7','Blue Yeti','USB Headset']} onChange={setDevice} accent={accent}/></Field>
          <Field label="Mic Gain" hint={gain === 1 ? 'default' : gain > 3 ? 'possible clipping' : ''}>
            <GainSlider value={gain} onChange={setGain} accent={accent} />
          </Field>
          <Field label="Volume" hint="playback / preview">
            <LinearSlider value={vol} min={0} max={1} step={0.01} onChange={setVol} accent={accent} format={v => `${Math.round(v * 100)}%`} />
          </Field>

          <div style={{ height: 16 }} />

          {/* HOTKEY */}
          <SectionTitle label="HOTKEY" num="02" />
          <Field label="Trigger"><HotkeyInput value={hotkey} accent={accent} /></Field>
          <Field label="Mode">
            <Toggle on={pushToTalk} onChange={setPushToTalk} accent={accent} />
            <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 10, color: 'var(--text-dim)', marginLeft: 8 }}>
              {pushToTalk ? 'push-to-talk · hold' : 'toggle · tap'}
            </span>
          </Field>

          <div style={{ height: 16 }} />

          {/* MODEL */}
          <SectionTitle label="MODEL" num="03" />
          <Field label="Engine"><Select value={model} options={['large-v3','medium','small','tiny']} onChange={setModel} accent={accent} /></Field>
          <Field label="Language"><Select value={lang} options={['auto','ru','en','de','fr','ja']} onChange={setLang} accent={accent} /></Field>
        </div>

        {/* footer */}
        <div style={{
          borderTop: '1px solid rgba(138,149,172,0.18)',
          padding: '8px 16px',
          display: 'flex', alignItems: 'center', gap: 8,
          fontFamily: 'JetBrains Mono, monospace', fontSize: 10,
          color: 'var(--text-dim)', letterSpacing: '0.08em',
        }}>
          <span>ESC · CLOSE</span>
          <span style={{ marginLeft: 'auto' }}>
            <button onClick={onClose} style={{
              fontFamily: 'Rajdhani, sans-serif', fontSize: 11, fontWeight: 600,
              letterSpacing: '0.2em',
              padding: '4px 14px',
              background: `color-mix(in oklab, var(--${accent}) 18%, transparent)`,
              border: `1px solid var(--${accent})`,
              color: `var(--${accent})`,
              cursor: 'pointer',
            }}>APPLY</button>
          </span>
        </div>
      </div>
    </div>
  );
}

window.Settings = Settings;
