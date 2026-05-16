// History panel — typography hierarchy, hover glow, selected glow
const { useState: useState_hist } = React;

const HISTORY_DATA = [
  { t: '08:43:14', dur: '00:04', lang: 'RU', text: 'Раз, два, три, четыре, пять.' },
  { t: '08:42:51', dur: '00:03', lang: 'RU', text: 'Раз, два, три, четыре, пять!' },
  { t: '08:41:02', dur: '00:11', lang: 'EN', text: 'Schedule a sync with the firmware team for Thursday.' },
  { t: '08:38:47', dur: '00:06', lang: 'EN', text: 'Ship the beta build to QA before end of day.' },
  { t: '08:35:19', dur: '00:08', lang: 'RU', text: 'Проверить логи перед деплоем, пожалуйста.' },
];

function HistoryRow({ row, idx, accent, selected, onClick, onMouseEnter }) {
  const [hover, setHover] = useState_hist(false);
  const accentCol = `var(--${accent})`;
  return (
    <div
      onClick={onClick}
      onMouseEnter={() => { setHover(true); onMouseEnter && onMouseEnter(); }}
      onMouseLeave={() => setHover(false)}
      style={{
        display: 'grid',
        gridTemplateColumns: '16px 68px 28px 1fr',
        columnGap: 10,
        alignItems: 'center',
        padding: '8px 14px',
        cursor: 'pointer',
        position: 'relative',
        borderLeft: `2px solid ${selected ? accentCol : hover ? 'rgba(138,149,172,0.35)' : 'transparent'}`,
        background: selected
          ? `linear-gradient(90deg, color-mix(in oklab, ${accentCol} 12%, transparent) 0%, transparent 60%)`
          : hover ? 'rgba(138,149,172,0.04)' : 'transparent',
        transition: 'background 140ms ease, border-color 140ms ease',
      }}
    >
      <span style={{
        fontFamily: 'JetBrains Mono, monospace', fontSize: 9,
        color: selected ? accentCol : 'var(--text-dim)',
        letterSpacing: '0.08em',
      }}>
        {String(idx + 1).padStart(2, '0')}
      </span>
      <span style={{
        fontFamily: 'JetBrains Mono, monospace', fontSize: 11,
        fontVariantNumeric: 'tabular-nums',
        color: selected ? 'var(--text-hi)' : 'var(--text-mid)',
        letterSpacing: '0.02em',
      }}>{row.t}</span>
      <span style={{
        fontFamily: 'Rajdhani, sans-serif', fontSize: 9,
        letterSpacing: '0.14em', fontWeight: 600,
        color: 'var(--text-dim)',
        border: '1px solid rgba(138,149,172,0.22)',
        padding: '1px 4px',
        textAlign: 'center',
      }}>{row.lang}</span>
      <span style={{
        fontFamily: 'JetBrains Mono, monospace', fontSize: 12,
        color: selected ? 'var(--text-hi)' : hover ? '#cfd6e4' : 'var(--text-mid)',
        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
      }}>{row.text}</span>

      {(hover || selected) && (
        <span style={{
          position: 'absolute', right: 10, top: '50%', transform: 'translateY(-50%)',
          fontFamily: 'Rajdhani, sans-serif', fontSize: 9, letterSpacing: '0.18em',
          color: selected ? accentCol : 'var(--text-dim)',
          fontWeight: 600,
        }}>
          {selected ? 'COPIED ✓' : 'COPY'}
        </span>
      )}
    </div>
  );
}

function History({ accent }) {
  const [sel, setSel] = useState_hist(null);
  return (
    <div style={{
      borderTop: '1px solid rgba(138,149,172,0.18)',
      background: 'var(--surface-0)',
      display: 'flex', flexDirection: 'column',
      flex: 1,
      minHeight: 0,
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10,
        padding: '10px 14px 8px 14px',
        borderBottom: '1px solid rgba(138,149,172,0.12)',
      }}>
        <span style={{
          fontFamily: 'Rajdhani, sans-serif', fontWeight: 600, fontSize: 11,
          letterSpacing: '0.22em', color: 'var(--text-hi)',
        }}>HISTORY</span>
        <span style={{
          fontFamily: 'JetBrains Mono, monospace', fontSize: 9,
          color: 'var(--text-dim)', letterSpacing: '0.08em',
        }}>LOG · {HISTORY_DATA.length} ENTRIES</span>
        <span style={{ marginLeft: 'auto', display: 'flex', gap: 4 }}>
          {[0,1,2,3,4].map(i => (
            <span key={i} style={{
              width: 3, height: 6,
              background: i < 3 ? `var(--${accent})` : 'rgba(138,149,172,0.2)',
              opacity: i < 3 ? 0.9 - i * 0.2 : 1,
            }} />
          ))}
        </span>
      </div>
      <div style={{ overflow: 'auto', flex: 1 }}>
        {HISTORY_DATA.map((row, i) => (
          <HistoryRow
            key={i}
            row={row}
            idx={i}
            accent={accent}
            selected={sel === i}
            onClick={() => setSel(sel === i ? null : i)}
          />
        ))}
      </div>
      <div style={{
        padding: '6px 14px',
        borderTop: '1px solid rgba(138,149,172,0.12)',
        display: 'flex', alignItems: 'center', gap: 14,
        fontFamily: 'JetBrains Mono, monospace', fontSize: 9,
        color: 'var(--text-dim)', letterSpacing: '0.1em',
      }}>
        <span>↑↓ NAVIGATE</span>
        <span>↵ COPY</span>
        <span>⌫ DELETE</span>
        <span style={{ marginLeft: 'auto', color: 'var(--text-mid)' }}>WHISPER · LARGE-V3</span>
      </div>
    </div>
  );
}

window.History = History;

// Compact variant — fixed height, header collapses to single line, ~3 rows visible.
function CompactHistory({ accent }) {
  const [sel, setSel] = useState_hist(null);
  const [collapsed, setCollapsed] = useState_hist(false);
  const height = collapsed ? 32 : 140;
  return (
    <div style={{
      borderTop: '1px solid rgba(138,149,172,0.18)',
      background: 'var(--surface-0)',
      display: 'flex', flexDirection: 'column',
      height,
      flexShrink: 0,
      transition: 'height 220ms ease',
      overflow: 'hidden',
    }}>
      <button
        onClick={() => setCollapsed(c => !c)}
        style={{
          display: 'flex', alignItems: 'center', gap: 8,
          padding: '8px 14px 6px 14px',
          background: 'transparent', border: 'none',
          borderBottom: collapsed ? 'none' : '1px solid rgba(138,149,172,0.10)',
          cursor: 'pointer', textAlign: 'left', width: '100%',
          color: 'inherit',
        }}
      >
        <span style={{
          fontFamily: 'Rajdhani, sans-serif', fontWeight: 600, fontSize: 10,
          letterSpacing: '0.22em', color: 'var(--text-hi)',
        }}>HISTORY</span>
        <span style={{
          fontFamily: 'JetBrains Mono, monospace', fontSize: 9,
          color: 'var(--text-dim)', letterSpacing: '0.08em',
        }}>· {HISTORY_DATA.length} ENTRIES</span>
        <span style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{
            fontFamily: 'JetBrains Mono, monospace', fontSize: 9,
            color: 'var(--text-dim)', letterSpacing: '0.08em',
          }}>WHISPER L-V3</span>
          <svg width="10" height="10" viewBox="0 0 10 10" style={{
            transform: collapsed ? 'rotate(-90deg)' : 'rotate(0deg)',
            transition: 'transform 220ms ease',
          }}>
            <polyline points="2,4 5,7 8,4" stroke="rgba(138,149,172,0.6)" strokeWidth="1.2" fill="none" />
          </svg>
        </span>
      </button>

      <div style={{ overflow: 'auto', flex: 1, minHeight: 0 }}>
        {HISTORY_DATA.map((row, i) => (
          <CompactHistoryRow
            key={i}
            row={row}
            idx={i}
            accent={accent}
            selected={sel === i}
            onClick={() => setSel(sel === i ? null : i)}
          />
        ))}
      </div>
    </div>
  );
}

function CompactHistoryRow({ row, idx, accent, selected, onClick }) {
  const [hover, setHover] = useState_hist(false);
  const accentCol = `var(--${accent})`;
  return (
    <div
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        display: 'grid',
        gridTemplateColumns: '14px 56px 22px 1fr 44px',
        columnGap: 8,
        alignItems: 'center',
        padding: '5px 14px',
        cursor: 'pointer',
        borderLeft: `2px solid ${selected ? accentCol : hover ? 'rgba(138,149,172,0.35)' : 'transparent'}`,
        background: selected
          ? `linear-gradient(90deg, color-mix(in oklab, ${accentCol} 12%, transparent) 0%, transparent 60%)`
          : hover ? 'rgba(138,149,172,0.04)' : 'transparent',
        transition: 'background 140ms ease, border-color 140ms ease',
      }}
    >
      <span style={{
        fontFamily: 'JetBrains Mono, monospace', fontSize: 9,
        color: selected ? accentCol : 'var(--text-dim)',
        letterSpacing: '0.06em',
      }}>{String(idx + 1).padStart(2, '0')}</span>
      <span style={{
        fontFamily: 'JetBrains Mono, monospace', fontSize: 10,
        fontVariantNumeric: 'tabular-nums',
        color: selected ? 'var(--text-hi)' : 'var(--text-mid)',
      }}>{row.t}</span>
      <span style={{
        fontFamily: 'Rajdhani, sans-serif', fontSize: 8,
        letterSpacing: '0.14em', fontWeight: 600,
        color: 'var(--text-dim)',
        border: '1px solid rgba(138,149,172,0.22)',
        padding: '1px 3px',
        textAlign: 'center',
      }}>{row.lang}</span>
      <span style={{
        fontFamily: 'JetBrains Mono, monospace', fontSize: 11,
        color: selected ? 'var(--text-hi)' : hover ? '#cfd6e4' : 'var(--text-mid)',
        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
      }}>{row.text}</span>
      <span style={{
        fontFamily: 'Rajdhani, sans-serif', fontSize: 9,
        letterSpacing: '0.16em', fontWeight: 600,
        textAlign: 'right',
        color: selected ? accentCol : hover ? 'var(--text-mid)' : 'transparent',
        transition: 'color 140ms ease',
      }}>{selected ? '✓ COPIED' : 'COPY'}</span>
    </div>
  );
}

window.CompactHistory = CompactHistory;
