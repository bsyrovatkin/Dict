// Streaming transcript view — words/chunks arrive every ~500ms during rec, decoding accumulates the final.
const { useEffect: useEffect_tx, useRef: useRef_tx, useState: useState_tx } = React;

const SAMPLE_CORPUS = [
  "Schedule a sync", "with the firmware team", "for Thursday afternoon",
  "about the OTA rollout.", "We need to confirm", "the staged percentages",
  "for the 1.4.2 release", "— five percent first,", "then twenty,", "then full ramp",
  "by next Wednesday.", "Also please loop in", "the QA leads", "so they can prepare",
  "the regression suite", "in advance.", "Make sure the changelog", "covers the new",
  "low-power capture mode", "and the bluetooth", "reconnect fix.", "I want screenshots",
  "of the metrics dashboard", "attached to the deck", "before the review.",
  "If the crash rate", "stays under zero point two", "we ship Friday.",
  "Otherwise hold for", "another bake cycle.", "Forward this", "to product",
  "and copy engineering.", "Then draft a one-pager", "summarising the call",
  "and send it out", "by end of day.", "That's it for now.",
];

// "Long" extension for the overflow demo
const SAMPLE_LONG_EXT = [
  "One more thing —", "let's verify the new", "telemetry pipeline",
  "is actually flushing", "every sixty seconds.", "The dashboard showed",
  "a gap last Tuesday", "between fourteen-oh-three", "and fourteen-thirteen",
  "that I want explained", "before we sign off.", "Pull the logs",
  "from the staging node,", "filter on event_id 7,", "and post the trace",
  "in the engineering channel.", "Reference ticket DICT-1142", "in the message",
  "so the on-call sees it.",
];

function TranscriptView({ state, length, accent }) {
  // length: 'empty' | 'short' | 'medium' | 'long'
  const [chunks, setChunks] = useState_tx([]);
  const cursorRef = useRef_tx(0); // index into corpus for next streamed chunk
  const scrollRef = useRef_tx(null);
  const stickyRef = useRef_tx(true);

  useEffect_tx(() => {
    // initial fill based on length tweak
    let initialN = 0;
    if (length === 'empty') initialN = 0;
    else if (length === 'short') initialN = 6;
    else if (length === 'medium') initialN = 18;
    else if (length === 'long') initialN = SAMPLE_CORPUS.length + 10;

    const initialChunks = [];
    for (let i = 0; i < initialN; i++) {
      const corpus = i < SAMPLE_CORPUS.length ? SAMPLE_CORPUS : SAMPLE_LONG_EXT;
      const idx = i < SAMPLE_CORPUS.length ? i : (i - SAMPLE_CORPUS.length) % SAMPLE_LONG_EXT.length;
      const age = i / Math.max(1, initialN - 1);
      initialChunks.push({ text: corpus[idx], age, fresh: false });
    }
    setChunks(initialChunks);
    cursorRef.current = initialN;
  }, [length]);

  // Streaming: append a chunk every 500ms while rec is active.
  useEffect_tx(() => {
    if (state === 'idle') return;
    const interval = state === 'rec' ? 500 : 700;
    const id = setInterval(() => {
      const i = cursorRef.current;
      if (i >= SAMPLE_CORPUS.length + SAMPLE_LONG_EXT.length * 2) return;
      const corpus = i < SAMPLE_CORPUS.length ? SAMPLE_CORPUS : SAMPLE_LONG_EXT;
      const idx = i < SAMPLE_CORPUS.length ? i : (i - SAMPLE_CORPUS.length) % SAMPLE_LONG_EXT.length;
      setChunks(prev => [...prev, { text: corpus[idx], age: 1, fresh: true }]);
      cursorRef.current = i + 1;
    }, interval);
    return () => clearInterval(id);
  }, [state, length]);

  // auto-scroll to bottom when stickyRef is true (user hasn't scrolled up)
  useEffect_tx(() => {
    if (!scrollRef.current) return;
    if (stickyRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [chunks]);

  // fade fresh chunks after a beat
  useEffect_tx(() => {
    const freshIdx = chunks.findIndex(c => c.fresh);
    if (freshIdx === -1) return;
    const t = setTimeout(() => {
      setChunks(prev => prev.map(c => c.fresh ? { ...c, fresh: false } : c));
    }, 380);
    return () => clearTimeout(t);
  }, [chunks]);

  const accentMap = { cyan: '#7be4ff', amber: '#ffb340', green: '#6bffb3', violet: '#c7a8ff' };
  const col = state === 'decoding' ? '#ffb340' : (accentMap[accent] || '#7be4ff');

  const onScroll = () => {
    const el = scrollRef.current; if (!el) return;
    const dist = el.scrollHeight - el.scrollTop - el.clientHeight;
    stickyRef.current = dist < 20;
  };
  const jumpToBottom = () => {
    if (!scrollRef.current) return;
    scrollRef.current.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
    stickyRef.current = true;
  };

  const wc = chunks.reduce((n, c) => n + c.text.split(/\s+/).filter(Boolean).length, 0);

  return (
    <div style={{
      flex: 1,
      display: 'flex', flexDirection: 'column',
      minHeight: 0,
      margin: '0 16px',
      border: '1px solid rgba(138,149,172,0.18)',
      background: 'var(--surface-2)',
      position: 'relative',
    }}>
      {/* corner brackets, dim */}
      {[[0, {top: -1, left: -1}], [90, {top: -1, right: -1}], [180, {bottom: -1, right: -1}], [270, {bottom: -1, left: -1}]].map(([rot, pos], i) => (
        <svg key={i} width="8" height="8" viewBox="0 0 8 8" style={{ position: 'absolute', transform: `rotate(${rot}deg)`, pointerEvents: 'none', ...pos }}>
          <polyline points="0,4 0,0 4,0" stroke={col} strokeWidth="1.2" fill="none" opacity="0.6" />
        </svg>
      ))}

      {/* panel header */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10,
        padding: '7px 12px', borderBottom: '1px solid rgba(138,149,172,0.12)',
        background: 'rgba(0,0,0,0.18)',
      }}>
        <span style={{
          fontFamily: 'JetBrains Mono, monospace', fontSize: 9,
          color: 'var(--text-dim)', letterSpacing: '0.12em',
        }}>TX/</span>
        <span style={{
          fontFamily: 'Rajdhani, sans-serif', fontWeight: 600, fontSize: 11,
          letterSpacing: '0.22em', color: 'var(--text-hi)', whiteSpace: 'nowrap',
        }}>{state === 'decoding' ? 'TRANSCRIBING' : 'LIVE TRANSCRIPT'}</span>
        <span style={{ flex: 1, height: 1, background: 'linear-gradient(90deg, rgba(138,149,172,0.18), transparent 60%)' }} />
        {/* mini activity indicator */}
        <ActivityDots state={state} col={col} />
        <span style={{
          fontFamily: 'JetBrains Mono, monospace', fontSize: 10,
          color: 'var(--text-mid)', fontVariantNumeric: 'tabular-nums',
        }}>{wc} <span style={{ color: 'var(--text-dim)' }}>WORDS</span></span>
      </div>

      {/* scroll body */}
      <div
        ref={scrollRef}
        onScroll={onScroll}
        className="transcript-scroll"
        style={{
          flex: 1, overflow: 'auto',
          padding: '12px 14px',
          fontFamily: '"JetBrains Mono", monospace',
          fontSize: 12.5,
          lineHeight: 1.65,
          letterSpacing: '0.01em',
          color: 'var(--text-mid)',
          scrollBehavior: 'auto',
          maskImage: 'linear-gradient(180deg, transparent 0, #000 14px, #000 calc(100% - 14px), transparent 100%)',
          WebkitMaskImage: 'linear-gradient(180deg, transparent 0, #000 14px, #000 calc(100% - 14px), transparent 100%)',
        }}
      >
        {chunks.length === 0 ? (
          <div style={{
            color: 'var(--text-dim)', fontStyle: 'italic',
            fontFamily: 'Rajdhani, sans-serif', fontSize: 13,
            letterSpacing: '0.06em',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            height: '100%', whiteSpace: 'nowrap',
          }}>
            <span>waiting for audio…</span>
          </div>
        ) : (
          <>
            {chunks.map((c, i) => {
              const isLast = i === chunks.length - 1;
              const isRecent = i >= chunks.length - 3;
              const fresh = c.fresh;
              const color = fresh ? '#ffffff' : isRecent ? 'var(--text-hi)' : 'var(--text-mid)';
              return (
                <span key={i} style={{
                  color,
                  background: fresh ? `color-mix(in oklab, ${col} 15%, transparent)` : 'transparent',
                  transition: 'background 380ms ease, color 380ms ease',
                  padding: fresh ? '0 2px' : 0,
                  marginLeft: i === 0 ? 0 : 0,
                }}>{c.text}{' '}</span>
              );
            })}
            {(state === 'rec' || state === 'decoding') && (
              <span style={{
                display: 'inline-block',
                width: 8, height: 14,
                background: col,
                verticalAlign: 'text-bottom',
                animation: 'caretBlink 1s steps(2) infinite',
                marginLeft: 1,
              }} />
            )}
          </>
        )}
      </div>

      {/* "jump to latest" pill — visible only when user scrolled away */}
      <JumpToLatest scrollRef={scrollRef} stickyRef={stickyRef} onClick={jumpToBottom} col={col} />

      {/* footer with row of dots showing chunk arrival cadence */}
      <div style={{
        padding: '5px 12px',
        borderTop: '1px solid rgba(138,149,172,0.10)',
        display: 'flex', alignItems: 'center', gap: 10,
        fontFamily: 'JetBrains Mono, monospace', fontSize: 9,
        color: 'var(--text-dim)', letterSpacing: '0.1em',
      }}>
        <CadenceTrack state={state} col={col} />
        <span style={{ marginLeft: 'auto' }}>{state === 'rec' ? 'STREAMING · 500MS' : state === 'decoding' ? 'FINALIZING · 700MS' : 'IDLE'}</span>
      </div>
    </div>
  );
}

function JumpToLatest({ scrollRef, stickyRef, onClick, col }) {
  const [show, setShow] = useState_tx(false);
  useEffect_tx(() => {
    const el = scrollRef.current; if (!el) return;
    const check = () => {
      const dist = el.scrollHeight - el.scrollTop - el.clientHeight;
      setShow(dist > 30);
    };
    el.addEventListener('scroll', check);
    check();
    return () => el.removeEventListener('scroll', check);
  }, []);
  if (!show) return null;
  return (
    <button onClick={onClick} style={{
      position: 'absolute', right: 12, bottom: 36,
      padding: '3px 10px',
      background: 'rgba(13,18,32,0.92)',
      border: `1px solid ${col}`,
      color: col,
      fontFamily: 'Rajdhani, sans-serif', fontWeight: 600, fontSize: 10,
      letterSpacing: '0.18em',
      cursor: 'pointer',
      display: 'inline-flex', alignItems: 'center', gap: 5,
    }}>
      ↓ JUMP TO LATEST
    </button>
  );
}

function ActivityDots({ state, col }) {
  if (state === 'idle') return null;
  return (
    <div style={{ display: 'flex', gap: 3 }}>
      {[0, 1, 2].map(i => (
        <span key={i} style={{
          width: 4, height: 4, borderRadius: '50%',
          background: col,
          animation: `txDot 1.2s ease-in-out ${i * 0.18}s infinite`,
        }} />
      ))}
    </div>
  );
}

// A 24-cell strip showing the last ~12 seconds of chunk arrivals (filled = chunk arrived).
function CadenceTrack({ state, col }) {
  const [bars, setBars] = useState_tx(() => Array(24).fill(0));
  useEffect_tx(() => {
    if (state === 'idle') { setBars(Array(24).fill(0)); return; }
    const id = setInterval(() => {
      setBars(prev => {
        const next = prev.slice(1);
        next.push(1);
        return next;
      });
    }, state === 'rec' ? 500 : 700);
    return () => clearInterval(id);
  }, [state]);
  return (
    <div style={{ display: 'flex', gap: 2, alignItems: 'center' }}>
      {bars.map((b, i) => (
        <span key={i} style={{
          width: 3, height: 6,
          background: b ? col : 'rgba(138,149,172,0.18)',
          opacity: b ? 0.4 + (i / bars.length) * 0.6 : 1,
        }} />
      ))}
    </div>
  );
}

window.TranscriptView = TranscriptView;
