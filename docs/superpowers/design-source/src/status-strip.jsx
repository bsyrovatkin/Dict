// Compact status strip — shown during rec/decoding in place of the big radar widget.
// Houses a small VU ring + STATE + timer + live level + peak readout.
const { useEffect: useEffect_cs, useRef: useRef_cs, useState: useState_cs } = React;

function CompactRing({ state, accent, size = 48 }) {
  const ref = useRef_cs(null);
  useEffect_cs(() => {
    const c = ref.current; if (!c) return;
    const dpr = window.devicePixelRatio || 1;
    c.width = size * dpr; c.height = size * dpr;
    c.style.width = size + 'px'; c.style.height = size + 'px';
    const ctx = c.getContext('2d');
    ctx.scale(dpr, dpr);

    const accentMap = { cyan: '#7be4ff', amber: '#ffb340', green: '#6bffb3', violet: '#c7a8ff' };
    const baseCol = state === 'rec' ? '#ff4757' : state === 'decoding' ? '#ffb340' : (accentMap[accent] || '#7be4ff');
    const dimCol = 'rgba(138,149,172,0.22)';

    const cx = size / 2, cy = size / 2;
    const bars = 36;
    const baseR = size * 0.32;
    let raf;
    const draw = () => {
      const t = performance.now() / 1000;
      ctx.clearRect(0, 0, size, size);

      // outer reticle ring
      ctx.strokeStyle = dimCol;
      ctx.lineWidth = 1;
      ctx.setLineDash([1, 2]);
      ctx.beginPath();
      ctx.arc(cx, cy, size * 0.46, 0, Math.PI * 2);
      ctx.stroke();
      ctx.setLineDash([]);

      // VU segments
      const segDeg = (360 / bars) - 2;
      for (let i = 0; i < bars; i++) {
        const cDeg = i * 360 / bars;
        const aMid = (cDeg - 90) * Math.PI / 180;
        let v;
        if (state === 'rec') v = 0.3 + Math.random() * 0.7 * (0.5 + 0.5 * Math.sin(t * 5 + i * 0.5));
        else if (state === 'decoding') v = 0.05;
        else v = 0;
        const maxH = size * 0.13;
        const h = 1 + v * maxH;
        ctx.strokeStyle = v > 0.6 ? baseCol : v > 0.2 ? `color-mix(in oklab, ${baseCol} 60%, transparent)` : 'rgba(138,149,172,0.18)';
        // computed-color trick: color-mix may not work in stroke. fallback:
        if (!CSS || !CSS.supports || !CSS.supports('color: color-mix(in oklab, red, blue)')) {
          ctx.strokeStyle = v > 0.6 ? baseCol : v > 0.2 ? baseCol : 'rgba(138,149,172,0.18)';
        }
        ctx.lineWidth = 1.6;
        const a0 = aMid - segDeg / 2 * Math.PI / 180;
        const a1 = aMid + segDeg / 2 * Math.PI / 180;
        ctx.beginPath();
        ctx.arc(cx, cy, baseR + h / 2, a0, a1);
        ctx.stroke();
      }

      // decoding spinner inside
      if (state === 'decoding') {
        const a0 = (t * 2.4) % (Math.PI * 2);
        ctx.strokeStyle = baseCol;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.arc(cx, cy, baseR - 4, a0, a0 + Math.PI * 0.85);
        ctx.stroke();
      }

      // inner pulse / dot
      if (state === 'rec') {
        const pulse = (Math.sin(t * 3.2) + 1) / 2;
        ctx.fillStyle = baseCol;
        ctx.fillRect(cx - 4, cy - 4, 8, 8);
        ctx.strokeStyle = `rgba(255,71,87,${0.3 + 0.4 * pulse})`;
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.arc(cx, cy, 8 + pulse * 4, 0, Math.PI * 2); ctx.stroke();
      } else if (state === 'decoding') {
        for (let i = -1; i <= 1; i++) {
          const pulse = (Math.sin(t * 4 - i) + 1) / 2;
          ctx.globalAlpha = 0.35 + 0.65 * pulse;
          ctx.fillStyle = baseCol;
          ctx.beginPath(); ctx.arc(cx + i * 4, cy, 1.5, 0, Math.PI * 2); ctx.fill();
        }
        ctx.globalAlpha = 1;
      }

      raf = requestAnimationFrame(draw);
    };
    draw();
    return () => cancelAnimationFrame(raf);
  }, [state, accent, size]);
  return <canvas ref={ref} style={{ display: 'block' }} />;
}

function LevelMeter({ state, accent, width = 96 }) {
  const ref = useRef_cs(null);
  useEffect_cs(() => {
    const c = ref.current; if (!c) return;
    const dpr = window.devicePixelRatio || 1;
    const W = width, H = 14;
    c.width = W * dpr; c.height = H * dpr;
    c.style.width = W + 'px'; c.style.height = H + 'px';
    const ctx = c.getContext('2d');
    ctx.scale(dpr, dpr);
    const accentMap = { cyan: '#7be4ff', amber: '#ffb340', green: '#6bffb3', violet: '#c7a8ff' };
    const col = state === 'rec' ? '#ff4757' : state === 'decoding' ? '#ffb340' : (accentMap[accent] || '#7be4ff');
    let raf;
    const segments = 28;
    const draw = () => {
      const t = performance.now() / 1000;
      ctx.clearRect(0, 0, W, H);
      const env = state === 'rec'
        ? Math.max(0.15, (Math.sin(t * 7) + Math.sin(t * 11) + 2) / 4 * 0.9)
        : state === 'decoding' ? 0.12 : 0;
      for (let i = 0; i < segments; i++) {
        const x = i * (W / segments);
        const lit = i / segments < env;
        const hot = i / segments > 0.85;
        ctx.fillStyle = lit
          ? (hot ? '#ff4757' : i / segments > 0.55 ? col : 'rgba(138,149,172,0.6)')
          : 'rgba(138,149,172,0.18)';
        ctx.fillRect(x, 2, (W / segments) - 1, H - 4);
      }
      raf = requestAnimationFrame(draw);
    };
    draw();
    return () => cancelAnimationFrame(raf);
  }, [state, accent, width]);
  return <canvas ref={ref} style={{ display: 'block' }} />;
}

function StatusStrip({ state, accent, elapsedStr }) {
  const accentMap = { cyan: '#7be4ff', amber: '#ffb340', green: '#6bffb3', violet: '#c7a8ff' };
  const col = state === 'rec' ? '#ff4757' : state === 'decoding' ? '#ffb340' : (accentMap[accent] || '#7be4ff');
  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: '48px auto 1fr auto auto auto',
      columnGap: 18,
      alignItems: 'center',
      padding: '12px 16px',
      borderBottom: '1px solid rgba(138,149,172,0.12)',
      background: `linear-gradient(180deg, color-mix(in oklab, ${col} 6%, transparent) 0%, transparent 100%)`,
    }}>
      <CompactRing state={state} accent={accent} size={48} />

      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        <span style={{
          fontFamily: 'JetBrains Mono, monospace', fontSize: 8,
          color: 'var(--text-dim)', letterSpacing: '0.18em', whiteSpace: 'nowrap',
        }}>{state === 'rec' ? 'CAPTURING' : 'PROCESSING'}</span>
        <span style={{
          fontFamily: 'Rajdhani, sans-serif', fontWeight: 700, fontSize: 14,
          letterSpacing: '0.22em', color: col,
          textShadow: `0 0 8px ${col}40`,
          whiteSpace: 'nowrap',
        }}>{state === 'rec' ? 'REC' : 'DECODE'}</span>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 18 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <span style={{
            fontFamily: 'JetBrains Mono, monospace', fontSize: 8,
            color: 'var(--text-dim)', letterSpacing: '0.18em', whiteSpace: 'nowrap',
          }}>ELAPSED</span>
          <span style={{
            fontFamily: 'JetBrains Mono, monospace', fontWeight: 500, fontSize: 17,
            color: 'var(--text-hi)', fontVariantNumeric: 'tabular-nums',
            letterSpacing: '0.04em', whiteSpace: 'nowrap',
          }}>{elapsedStr}</span>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <span style={{
            fontFamily: 'JetBrains Mono, monospace', fontSize: 8,
            color: 'var(--text-dim)', letterSpacing: '0.18em', whiteSpace: 'nowrap',
          }}>LEVEL</span>
          <LevelMeter state={state} accent={accent} width={84} />
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 2, alignItems: 'flex-end' }}>
        <span style={{
          fontFamily: 'JetBrains Mono, monospace', fontSize: 8,
          color: 'var(--text-dim)', letterSpacing: '0.18em', whiteSpace: 'nowrap',
        }}>PEAK</span>
        <span style={{
          fontFamily: 'JetBrains Mono, monospace', fontWeight: 500, fontSize: 12,
          color: 'var(--text-hi)', fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap',
        }}>{state === 'rec' ? '-3.2 dB' : '-6.1 dB'}</span>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 2, alignItems: 'flex-end' }}>
        <span style={{
          fontFamily: 'JetBrains Mono, monospace', fontSize: 8,
          color: 'var(--text-dim)', letterSpacing: '0.18em', whiteSpace: 'nowrap',
        }}>MODEL</span>
        <span style={{
          fontFamily: 'Rajdhani, sans-serif', fontWeight: 600, fontSize: 12,
          letterSpacing: '0.18em', color: 'var(--text-hi)', whiteSpace: 'nowrap',
        }}>L·V3</span>
      </div>
    </div>
  );
}

window.StatusStrip = StatusStrip;
window.LevelMeter = LevelMeter;
window.CompactRing = CompactRing;
