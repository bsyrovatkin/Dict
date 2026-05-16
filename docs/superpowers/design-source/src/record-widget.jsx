// Record widget — layered concentric arcs, radar sweep on idle, VU bars, peak marker.
// State: idle | rec | decoding
const { useEffect, useRef, useState } = React;

function RecordWidget({ state, accent, ringDensity, size = 360 }) {
  const canvasRef = useRef(null);
  const rafRef = useRef(0);
  const startRef = useRef(performance.now());
  const vuRef = useRef(new Array(ringDensity).fill(0));
  const peakRef = useRef({ idx: 0, val: 0, t: 0 });

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const internalSize = 360;
    canvas.width = internalSize * dpr;
    canvas.height = internalSize * dpr;
    canvas.style.width = internalSize + 'px';
    canvas.style.height = internalSize + 'px';
    ctx.scale(dpr, dpr);
    // Visible line weight stays a constant value relative to internal space;
    // since the wrapper is CSS-scaled, lines get visually thinner at small sizes —
    // we beef them up here so they survive shrinking to ~200px.
    const px = Math.max(1, internalSize / size);

    // All drawing uses an internal 360x360 coordinate space; ctx.scale handles the rest.
    const cx = internalSize / 2, cy = internalSize / 2;

    const palette = {
      cyan:   { hi: '#7be4ff', mid: '#2ea8c9', dim: 'rgba(123,228,255,0.18)', ink: 'rgba(123,228,255,0.45)' },
      amber:  { hi: '#ffb340', mid: '#c47a14', dim: 'rgba(255,179,64,0.18)', ink: 'rgba(255,179,64,0.45)' },
      green:  { hi: '#6bffb3', mid: '#1fa36a', dim: 'rgba(107,255,179,0.18)', ink: 'rgba(107,255,179,0.45)' },
      violet: { hi: '#c7a8ff', mid: '#7a4fd1', dim: 'rgba(199,168,255,0.18)', ink: 'rgba(199,168,255,0.45)' },
      rec:    { hi: '#ff4757', mid: '#b4202e', dim: 'rgba(255,71,87,0.18)', ink: 'rgba(255,71,87,0.45)' },
    };
    const col = state === 'rec' ? palette.rec : palette[accent] || palette.cyan;
    const structural = 'rgba(138,149,172,0.22)';
    const structuralDim = 'rgba(138,149,172,0.10)';

    const tick = (now) => {
      try {
      const t = (now - startRef.current) / 1000;
      ctx.clearRect(0, 0, internalSize, internalSize);

      // update VU envelope
      if (state === 'rec') {
        for (let i = 0; i < ringDensity; i++) {
          const target = 0.25 + Math.random() * 0.75 * (0.5 + 0.5 * Math.sin(t * 6 + i * 0.4));
          vuRef.current[i] += (target - vuRef.current[i]) * 0.35;
        }
      } else if (state === 'decoding') {
        for (let i = 0; i < ringDensity; i++) {
          vuRef.current[i] += (0.08 - vuRef.current[i]) * 0.2;
        }
      } else {
        for (let i = 0; i < ringDensity; i++) {
          vuRef.current[i] += (0 - vuRef.current[i]) * 0.15;
        }
      }
      // peak tracker
      let maxI = 0, maxV = 0;
      for (let i = 0; i < ringDensity; i++) if (vuRef.current[i] > maxV) { maxV = vuRef.current[i]; maxI = i; }
      if (maxV > peakRef.current.val - (now - peakRef.current.t) * 0.0008) {
        peakRef.current = { idx: maxI, val: maxV, t: now };
      }

      // --- outer reticle frame (cardinal ticks at N/E/S/W) ---
      ctx.strokeStyle = structural;
      ctx.lineWidth = px;
      const R_OUT = 170;
      // 4 cardinal tick marks
      for (const ang of [0, 90, 180, 270]) {
        const a = (ang - 90) * Math.PI / 180;
        const x1 = cx + Math.cos(a) * (R_OUT - 10);
        const y1 = cy + Math.sin(a) * (R_OUT - 10);
        const x2 = cx + Math.cos(a) * (R_OUT + 4);
        const y2 = cy + Math.sin(a) * (R_OUT + 4);
        ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
      }
      // corner brackets
      ctx.strokeStyle = col.ink;
      ctx.lineWidth = px;
      const BR = R_OUT + 8;
      const bracketLen = 14;
      for (const [qx, qy] of [[-1,-1],[1,-1],[1,1],[-1,1]]) {
        const ox = cx + qx * BR * 0.68;
        const oy = cy + qy * BR * 0.68;
        ctx.beginPath();
        ctx.moveTo(ox + qx * bracketLen, oy);
        ctx.lineTo(ox, oy);
        ctx.lineTo(ox, oy + qy * bracketLen);
        ctx.stroke();
      }

      // --- 3 concentric structural rings (dotted fade) ---
      ctx.strokeStyle = structuralDim;
      ctx.lineWidth = px;
      ctx.setLineDash([1, 3]);
      [165, 140, 120].forEach(r => {
        ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.stroke();
      });
      ctx.setLineDash([]);

      // --- degree ticks (every 15°) on inner structural ring ---
      ctx.strokeStyle = 'rgba(138,149,172,0.35)';
      ctx.lineWidth = px;
      for (let deg = 0; deg < 360; deg += 15) {
        const a = (deg - 90) * Math.PI / 180;
        const major = deg % 45 === 0;
        const r1 = 120 - (major ? 6 : 3);
        const r2 = 120;
        ctx.beginPath();
        ctx.moveTo(cx + Math.cos(a) * r1, cy + Math.sin(a) * r1);
        ctx.lineTo(cx + Math.cos(a) * r2, cy + Math.sin(a) * r2);
        ctx.stroke();
      }

      // --- radar sweep (idle only) ---
      if (state === 'idle') {
        const sweepA = (t * 0.6) % (Math.PI * 2);
        const grad = ctx.createConicGradient ? ctx.createConicGradient(sweepA - Math.PI/2, cx, cy) : null;
        if (grad) {
          grad.addColorStop(0, col.ink);
          grad.addColorStop(0.15, 'transparent');
          grad.addColorStop(1, 'transparent');
          ctx.fillStyle = grad;
          ctx.beginPath();
          ctx.arc(cx, cy, 118, 0, Math.PI * 2);
          ctx.arc(cx, cy, 72, 0, Math.PI * 2, true);
          ctx.fill();
        } else {
          // fallback: solid wedge
          ctx.fillStyle = col.dim;
          ctx.beginPath();
          ctx.moveTo(cx, cy);
          ctx.arc(cx, cy, 118, sweepA - 0.5, sweepA);
          ctx.closePath();
          ctx.fill();
        }
      }

      // --- decoding spinner arc (between rings) ---
      if (state === 'decoding') {
        const span = Math.PI * 0.8;
        const a0 = (t * 2.2) % (Math.PI * 2);
        ctx.strokeStyle = col.hi;
        ctx.lineWidth = 2 * px;
        ctx.beginPath();
        ctx.arc(cx, cy, 110, a0, a0 + span);
        ctx.stroke();
        // tail
        ctx.strokeStyle = col.ink;
        ctx.lineWidth = 2 * px;
        ctx.beginPath();
        ctx.arc(cx, cy, 110, a0 - 0.4, a0);
        ctx.stroke();
      }

      // --- VU ring: ringDensity segments between r=84 and r=108 ---
      const seg = ringDensity;
      const gapDeg = seg >= 72 ? 1.8 : 2.4;
      const segDeg = (360 / seg) - gapDeg;
      for (let i = 0; i < seg; i++) {
        const cDeg = (i * 360 / seg);
        const aMid = (cDeg - 90) * Math.PI / 180;
        const v = Math.max(0, Math.min(1, vuRef.current[i]));
        const baseR = 84;
        const maxH = 26;
        const h = 2 + v * maxH;
        // color graded by amplitude
        let c;
        if (state === 'idle') {
          c = v > 0.01 ? col.hi : col.dim;
        } else if (state === 'decoding') {
          c = col.dim;
        } else {
          if (v > 0.85) c = '#ffffff';
          else if (v > 0.55) c = col.hi;
          else c = col.mid;
        }
        ctx.strokeStyle = c;
        ctx.lineWidth = (Math.PI * 2 * (baseR + h/2)) / seg - gapDeg * Math.PI / 180 * (baseR + h/2);
        ctx.lineWidth = Math.max(1.2 * px, ctx.lineWidth * 0.9);
        const a0 = aMid - (segDeg/2) * Math.PI / 180;
        const a1 = aMid + (segDeg/2) * Math.PI / 180;
        ctx.beginPath();
        ctx.arc(cx, cy, baseR + h/2, a0, a1);
        ctx.stroke();
      }

      // peak/clip marker
      if (state === 'rec' && peakRef.current.val > 0.5) {
        const pAng = (peakRef.current.idx * 360 / seg - 90) * Math.PI / 180;
        const rr = 84 + 26 + 6;
        const peakX = cx + Math.cos(pAng) * rr;
        const peakY = cy + Math.sin(pAng) * rr;
        ctx.fillStyle = peakRef.current.val > 0.92 ? '#ffffff' : col.hi;
        ctx.beginPath();
        // chevron triangle pointing inward
        const tAng = pAng + Math.PI;
        const tip = 5;
        ctx.moveTo(peakX + Math.cos(tAng + 0.35) * tip, peakY + Math.sin(tAng + 0.35) * tip);
        ctx.lineTo(peakX, peakY);
        ctx.lineTo(peakX + Math.cos(tAng - 0.35) * tip, peakY + Math.sin(tAng - 0.35) * tip);
        ctx.closePath();
        ctx.fill();
      }

      // --- inner core ring ---
      const coreR = 58;
      ctx.strokeStyle = state === 'rec' ? col.hi : col.mid;
      ctx.lineWidth = (state === 'rec' ? 2 : 1.25) * px;
      ctx.beginPath(); ctx.arc(cx, cy, coreR, 0, Math.PI * 2); ctx.stroke();

      // pulse ring (rec)
      if (state === 'rec') {
        const pulse = (Math.sin(t * 3.2) + 1) / 2;
        ctx.strokeStyle = `rgba(255,71,87,${0.18 + 0.22 * pulse})`;
        ctx.lineWidth = px;
        ctx.beginPath(); ctx.arc(cx, cy, coreR + 6 + pulse * 6, 0, Math.PI * 2); ctx.stroke();
      }

      // core glyph
      ctx.save();
      ctx.translate(cx, cy);
      if (state === 'idle') {
        // play triangle
        ctx.fillStyle = col.hi;
        ctx.beginPath();
        ctx.moveTo(-10, -14);
        ctx.lineTo(16, 0);
        ctx.lineTo(-10, 14);
        ctx.closePath();
        ctx.fill();
      } else if (state === 'rec') {
        // rec square + small elapsed timer ring behind
        ctx.fillStyle = '#ffffff';
        ctx.fillRect(-10, -10, 20, 20);
      } else {
        // decoding: three dots
        ctx.fillStyle = col.hi;
        for (let i = -1; i <= 1; i++) {
          const pulse = (Math.sin(t * 4 - i) + 1) / 2;
          ctx.globalAlpha = 0.4 + 0.6 * pulse;
          ctx.beginPath(); ctx.arc(i * 12, 0, 3, 0, Math.PI * 2); ctx.fill();
        }
        ctx.globalAlpha = 1;
      }
      ctx.restore();

      // center crosshair micro-mark
      ctx.strokeStyle = 'rgba(205,215,235,0.25)';
      ctx.lineWidth = px;
      ctx.beginPath();
      ctx.moveTo(cx - 3, cy); ctx.lineTo(cx + 3, cy);
      ctx.moveTo(cx, cy - 3); ctx.lineTo(cx, cy + 3);
      ctx.stroke();

      rafRef.current = requestAnimationFrame(tick);
      } catch (err) {
        console.error('[RecordWidget tick]', err);
      }
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, [state, accent, ringDensity, size]);

  const scale = size / 360;
  return (
    <div style={{ width: size, height: size, overflow: 'hidden', position: 'relative', margin: '0 auto' }}>
      <div style={{
        width: 360, height: 360,
        transform: `scale(${scale})`, transformOrigin: 'top left',
      }}>
        <canvas ref={canvasRef} style={{ display: 'block' }} />
      </div>
    </div>
  );
}
window.RecordWidget = RecordWidget;
