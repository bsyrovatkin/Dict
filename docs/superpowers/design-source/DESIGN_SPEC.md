# Dict — HUD Interface Specification

Hi-fi sci-fi desktop dictation app. Single 560×680 window, dark, holographic-instrument aesthetic. Whisper-based STT with real-time chunked transcription.

---

## 1. Window & Shell

- **Size:** 560 × 680 px, fixed (non-resizable for v1).
- **Surface stack:**
  - `--bg`: `#03040a` (outside)
  - `--surface-0`: `#070a14` (history zone)
  - `--surface-1`: `#0a0e1a` (main body)
  - `--surface-2`: `#0d1220` (transcript card, settings)
- **Window border:** 1px `rgba(138,149,172,0.18)` + 6px outer ring `rgba(138,149,172,0.03)`.
- **State-tinted outer glow:** 70px box-shadow tinted by current state.
  - idle → accent (cyan default)
  - rec → `#ff4757` crimson
  - decoding → `#ffb340` amber
- **Corner brackets:** 12px L-shaped polylines at all four window corners, in the active state color. 1.5px stroke.

## 2. Type System

- **Display / labels:** Rajdhani (400/500/600/700). All-caps with 0.14–0.28em tracking.
- **Mono / numeric / transcript body:** JetBrains Mono (300/400/500/600). `font-variant-numeric: tabular-nums` for all timers and dB readouts.
- **Sizes (do not go smaller):**
  - Section labels (uppercase Rajdhani): 8–11px
  - Body / transcript: 12–13px
  - Large readouts (STATE, ELAPSED): 14–20px
  - DICT wordmark: 18px

## 3. Color & State Tokens

```
--cyan:    #7be4ff   --cyan-deep:    #2ea8c9
--amber:   #ffb340   --amber-deep:   #c47a14
--green:   #6bffb3   --green-deep:   #1fa36a
--violet:  #c7a8ff   --violet-deep:  #7a4fd1
--crimson: #ff4757   --crimson-deep: #b4202e

--text-hi:  #e6edf7
--text-mid: #8a95ac
--text-dim: #4a5268
```

User-pickable accent: cyan (default) / amber / green / violet — applied to idle radar, focus rings, slider fills, selected history rows. **Crimson** is reserved for REC state and clipping warnings. **Amber** is reserved for DECODING (even when accent is otherwise).

## 4. Layout (top → bottom)

Single layout, same in every state. Widget never moves or resizes.

```
┌────────────────────────────────────────────────┐
│  Header                                  56 px │
├────────────────────────────────────────────────┤
│  Capture zone:                          ~200px │
│  [200×200 radar]  STATE / ELAPSED / PEAK /     │
│                   LEVEL meter                  │
├────────────────────────────────────────────────┤
│  CTA bar: PRESS [F9] TO …               ~32 px │
├────────────────────────────────────────────────┤
│  Transcript panel (always visible)      flex 1 │
│  scrolls when text overflows                   │
├────────────────────────────────────────────────┤
│  History (collapsible)              140 / 32px │
└────────────────────────────────────────────────┘
```

## 5. Header

- DICT wordmark (Rajdhani 700, 18px, 0.32em tracking).
- Status indicator: 18×18 SVG, concentric circles, center dot in state color.
- Hotkey slab: monospace 10px, label "HOTKEY" + key. Outlined chip with clip-path bevel.
- Status pill: `READY` / `REC ●` (pulsing dot) / `DECODING` (spinner). Bevelled clip-path on top-left + bottom-right corners.
- Mini waveform strip (toggleable): 120×22 canvas, 36 bars, last ~6 bars in state color, rest dim grey.
- Window controls: settings ⚙, minimize, close. 28×24 each, hover bg `rgba(138,149,172,0.12)`.
- Bottom divider: 1px gradient line fading at edges.

## 6. Record Widget (radar)

Always 200×200 (visually). Internally drawn in 360×360 coordinate space, then CSS `transform: scale(0.555)`. Canvas + requestAnimationFrame loop.

**Always-on geometry:**
- Outer reticle: 4 cardinal tick marks at N/E/S/W (radius 170, length 14).
- 4 corner L-brackets in state color, at radius ~178, length 14.
- 3 concentric dotted rings (r=120, 140, 165), `setLineDash([1,3])`, dim grey.
- 15°-spaced tick marks on inner ring at r=120, with 6px ticks at 45°-multiples, 3px otherwise.
- Inner core ring at r=58. Thicker (2px) when REC, thin otherwise.
- Center crosshair (3px arms).

**Per-state additions:**
- **IDLE:** conic-gradient radar sweep rotating clockwise. Center glyph: play triangle (state-color fill).
- **REC:** VU ring of N segments (54 / 72 / 96 — user-settable) between r=84 and r=110; segment height ∝ amplitude. White peak chevrons appear at r=116 for samples > 0.92. Pulsing concentric ring around the core (1.8s sine). Center glyph: white 20×20 square.
- **DECODING:** spinner arc at r=110 (220° sweep, rotating). Center glyph: three dots with phase-offset pulse.

**VU palette grading by amplitude:**
- `> 0.92` → white (clip)
- `> 0.55` → state color hi
- `> 0.0` → state color mid
- else → faint state color dim

## 7. Capture Zone Meta (right of radar)

Two-column grid (label 56px / value 1fr), gap 10px between rows:

1. **STATE** — value in 20px Rajdhani 700, accent or state color, text-shadow `0 0 8px <color>55`.
2. *divider line*
3. **ELAPSED** — `MM:SS.D`, tabular mono 14px.
4. **PEAK** — `-3.2 dB` / `-∞ dB`, mono 14px.
5. *divider line*
6. **LEVEL** — 28-segment horizontal VU bar (140px wide × 14px tall). Bars colored: `> 0.85` crimson, `> 0.55` state color, else grey-dim.

## 8. CTA Bar

Centered row, padding 7×16px:
```
PRESS  [F9]  TO START DICTATION       (idle)
PRESS  [F9]  TO STOP & TRANSCRIBE     (rec)
PRESS  [F9]  TO CANCEL DECODING       (decoding)
```
F9 chip: JetBrains Mono 600 11px, bevelled clip-path corners. Border + faint fill in state color when not idle.

## 9. Transcript Panel (TX/)

Always present. Surface `--surface-2`, 1px border `rgba(138,149,172,0.18)`, with small corner brackets in state color.

**Panel header:**
- Left: `TX/` dim label + `LIVE TRANSCRIPT` (when rec) / `TRANSCRIBING` (when decoding) / `LIVE TRANSCRIPT` (when idle).
- Right: 3-dot activity animation (visible only when not idle) + word count (`128 WORDS`).

**Body:**
- JetBrains Mono 12.5px, line-height 1.65.
- Color grading by recency:
  - Newest chunk (`fresh: true` for ~380ms): white text on `color-mix(state-color 15%, transparent)` background, padding `0 2px`.
  - Last 3 chunks: `--text-hi`.
  - Older: `--text-mid`.
- Blinking caret (▊, 8×14, state color) at the very end while rec/decoding.
- Top + bottom 14px linear-gradient mask so text "fades into" the scroll region.
- Auto-scroll to bottom while user is near bottom (within 20px). If user scrolls up, auto-scroll pauses and a **"↓ JUMP TO LATEST"** pill appears (bottom-right, bordered in state color).

**Empty state:** centered italic Rajdhani 13px text: `waiting for audio…` (`--text-dim`).

**Footer:**
- Cadence track: 24 thin vertical bars (3×6px), each lights up as a chunk arrives — visualizes streaming cadence.
- Right side: `STREAMING · 500MS` / `FINALIZING · 700MS` / `IDLE`.

## 10. Streaming Behavior

- **REC:** chunks arrive every **500 ms**. Each chunk = 2–6 words. Append-only.
- **DECODING:** chunks arrive every **700 ms**, with the same visual treatment but amber tint.
- Track via a `cursorRef` to avoid React stale-closure bugs (don't read `chunks.length` in the interval — use a ref).
- Fresh-flag clears 380ms after the chunk is added.

## 11. History (compact, collapsible)

Fixed 140px expanded, 32px collapsed (`transition: height 220ms`). Header is a button:

```
HISTORY  ·  5 ENTRIES                WHISPER L-V3   ▾
```

Click anywhere on header → toggle. Chevron rotates -90° when collapsed.

**Row layout (grid):**
```
[##] [HH:MM:SS] [RU] [text………]                  COPY
14px   56px      22px  1fr                       44px
```

- Row #: monospace 9px, dim. Becomes accent when selected.
- Timestamp: mono 10px, tabular nums.
- Language tag: Rajdhani 8px bold, 0.14em tracking, in a 1px outlined box.
- Text: monospace 11px, ellipsized.
- Right action: appears on hover (`COPY`), changes to `✓ COPIED` (accent color) when row is selected.
- Selected row: 2px left border in accent + horizontal gradient bg `color-mix(accent 12% → transparent at 60%)`.
- Hover row: 2px left border in grey-mid + faint bg.

## 12. Settings Dialog

Modal overlay, 496px wide, max 620px tall, centered. `rgba(3,4,10,0.72)` backdrop with `backdrop-filter: blur(2px)`.

- 1px border + accent-color corner brackets at all four corners.
- Header: `CFG/ SETTINGS` + close × button.
- Sections (each with `§01 LABEL` + dim gradient hairline):
  - **§01 AUDIO** — Input (Select), Mic Gain (custom log slider), Volume (linear slider).
  - **§02 HOTKEY** — Trigger (rebind), Mode (push-to-talk toggle + descriptor text).
  - **§03 MODEL** — Engine (Select: large-v3, medium, small, tiny), Language (Select: auto, ru, en, de, fr, ja).
- Footer: `ESC · CLOSE` left, `APPLY` button right (accent color border + fill).

**Field row:** 96px label column / 1fr control column. Min height 28px, margin-bottom 8px. Label is uppercase Rajdhani 11px, 0.14em tracking.

**Mic Gain slider (custom):**
- Log-scale, range 0.5×–5×.
- Track: 2px line + 5 minor tick marks.
- Two callouts on the track: `1×` (default, light grey vertical line) and `CLIP` (red vertical line at 3×).
- Fill is accent color up to 3×, switches to crimson past it.
- Thumb: 10×14 rectangle, surface bg + 1px state-color border.
- Live preview row below: a label (`LIVE` or `HOT`), a 140×10 mini bars canvas (animated, scaled by gain), and current value `1.00×`.

**Linear slider (Volume):**
- Same look but linear, with 5 tick marks at 0/25/50/75/100%.

**Toggles:** 32×16 px, accent-colored bg + border when on. Inner 10×10 fill animates left/right.

**Select dropdowns:** flat, monospace, accent-colored bottom-left border + chevron in accent color. Selected item highlighted with accent left-border.

## 13. Scroll & Overflow

Three places in the UI have scroll:

1. **Transcript panel** — primary scroll. 8px scrollbar with `rgba(138,149,172,0.35)` thumb. Top/bottom mask gradient. Sticky-to-bottom autoscroll + jump-to-latest pill.
2. **History panel** — 6px scrollbar, hidden when content fits.
3. **Settings dialog body** — 6px scrollbar when fields overflow 540px.

Everywhere else uses fixed sizing and never scrolls.

## 14. Animations (motion budget)

- **Status dots (`pulseDot`, `txDot`):** 1–1.2s ease-in-out infinite.
- **REC core pulse ring:** sine wave, 3.2 Hz.
- **Decoding spinner:** 0.9s linear infinite (CSS) or 2.2 rad/s on canvas.
- **Radar sweep (idle):** 0.6 rad/s, conic gradient.
- **Fresh-chunk highlight:** 380 ms fade out (background + color).
- **History expand/collapse:** 220 ms ease.
- **State-glow outer shadow:** 320 ms ease cross-fade.
- **Cadence-bar fill:** discrete tick every 500/700ms.

## 15. Implementation Notes

- All numeric readouts use `font-variant-numeric: tabular-nums` to prevent jitter.
- Every label that could wrap onto two lines must have `white-space: nowrap`. Watch especially: model names ("L·V3" not "L-V3"), state pills, meta labels.
- Use `color-mix(in oklab, <accent> X%, transparent)` for tinted fills — keep accent var as single source of truth.
- All clip-path bevels: `polygon(6px 0, 100% 0, 100% calc(100% - 6px), calc(100% - 6px) 100%, 0 100%, 0 6px)`.
- For React: each effect that schedules `requestAnimationFrame` must `cancelAnimationFrame` in cleanup. Track corpus cursor via `useRef`, never via stale closure of `chunks.length`.

## 16. Accessibility

- Hotkey is global (OS-level), but the F9 chip in the CTA must also be a focusable button.
- All status-only color cues (REC red, DECODE amber) are also reinforced by:
  - Different center glyph (square / dots / triangle)
  - Different status-pill text label
  - Different CTA verb
- Min touch/click target on chrome buttons: 24×28 (current spec). Keep.
