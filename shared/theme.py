"""
Design tokens for Canvas Downloader UI.

Import and use these constants instead of hardcoding hex values.

──────────────────────────────────────────────────────────────────────────────
HOW TO PICK A COLOUR  (read this before adding a hex anywhere)
──────────────────────────────────────────────────────────────────────────────
Every colour below sits on a **ramp** - an ordered run of shades from light to
dark. When you need a colour, step along the nearest ramp; do NOT invent a
neighbouring hex.

That single rule is the whole point of this file. A 2026-07-25 sweep found 229
distinct hex values against 25 tokens, and the extras were not design decisions -
they were drift: ``#0f1117`` beside ``#0e1117``, ``#2d3148`` beside ``BG_CARD``'s
``#2d3248`` (a digit transposition), four separate attempts at the same near-black.
Each was individually invisible - under 1.0 CIEDE2000, i.e. below the threshold of
human perception - but collectively they made the palette impossible to reason
about or retheme.

``scripts/verify_architecture.py`` Rule 8 now fails the build on any NEW hex that
lands within 1.0 CIEDE2000 of a token defined here, and names the token to use
instead. If Rule 8 flags you, the answer is essentially always "use the token" -
a difference that small is not a design decision anyone can see.

Deliberate close neighbours DO exist and are legitimate: ``styles/sync_history_cards.css``
documents a 4-level depth ramp whose adjacent tiers sit under 1.0 apart on purpose,
because they encode nesting depth rather than a visual difference. Those live in
their own file with an explanatory comment - which is exactly the bar for keeping a
near-duplicate out of this file.
"""

# ── Core neutrals ────────────────────────────────────────────────────────────
WHITE           = "#ffffff"
TEXT_PRIMARY    = WHITE          # alias: primary text is pure white on this dark UI

# Slate ramp - the app's main text/border ramp (cool, slightly blue-grey).
# TEXT_SLATE_200 is the single most-used colour in the app after pure white.
TEXT_SLATE_50   = "#f8fafc"
TEXT_SLATE_100  = "#f1f5f9"
TEXT_SLATE_200  = "#e2e8f0"
TEXT_SLATE_300  = "#cbd5e1"
TEXT_SLATE_400  = "#94a3b8"
TEXT_SLATE_500  = "#64748b"
TEXT_SLATE_600  = "#475569"

# Gray ramp - neutral (no blue cast). Used where slate would read too cool.
TEXT_GRAY_100   = "#f3f4f6"
TEXT_GRAY_200   = "#e5e7eb"
TEXT_LIGHT      = "#d1d5db"      # gray-300
TEXT_GRAY_400   = "#9ca3af"
TEXT_GRAY_500   = "#6b7280"

# Legacy neutrals kept because they are referenced directly and are NOT on a ramp.
TEXT_SECONDARY  = "#8a91a6"
TEXT_MUTED      = "#666666"
TEXT_DIM        = "#888888"
TEXT_MID        = "#a0a0a0"      # mid grey, disabled/secondary labels
TEXT_STEEL      = "#c7ccd9"      # light blue-grey body text
TEXT_STATUS     = "#8b949e"      # muted status text ("No Changes", timestamps)

# ── Backgrounds ──────────────────────────────────────────────────────────────
BG_DARK         = "#1a1d27"
BG_CARD         = "#2d3248"
BG_CARD_HOVER   = "#3e4353"
BG_TERMINAL     = "#0d1117"
BG_PAGE         = "#1a1a2e"

# ── Accent / Brand ───────────────────────────────────────────────────────────
ACCENT_BLUE     = "#4da8da"
ACCENT_LINK     = "#38bdf8"
ACCENT_CYAN     = "#3fd9ff"      # "core content" accent (tags, highlights)
BLUE_PRIMARY    = "#3b82f6"
BLUE_DEEP       = "#1f77b4"      # deeper blue for filled bars / solid backgrounds

# ── Status ───────────────────────────────────────────────────────────────────
SUCCESS         = "#4ade80"
SUCCESS_ALT     = "#2ecc71"
SUCCESS_STAT    = "#10b981"      # emerald, used for metric values (speed, counts)
ERROR           = "#ef4444"
ERROR_ALT       = "#e74c3c"
ERROR_LIGHT     = "#f87171"
ERROR_BG        = "#2c1616"
DANGER          = "#ff4b4b"      # Streamlit's own red - destructive actions
WARNING         = "#f59e0b"
WARNING_ALT     = "#f1c40f"
WARNING_AMBER   = "#fbbf24"
WARNING_YELLOW  = "#facc15"

# ── Pipeline phase colours ───────────────────────────────────────────────────
# One colour per phase of a run, so a phase reads the same everywhere it appears
# (progress dashboard, stat cards, tags, spinners).
PHASE_PANOPTO   = "#b89dfe"      # purple  - Panopto audio/video
PHASE_PROCESS   = "#f97316"      # orange  - post-processing / conversions
PHASE_SECONDARY = "#68d4a3"      # mint    - secondary Canvas content

# ── Borders ──────────────────────────────────────────────────────────────────
# Intentionally the same value as BG_CARD: a card's border reads as the next
# surface up in the depth ramp. Kept as a separate name so the two can diverge.
BORDER_DEFAULT  = "#2d3248"
BORDER_TERMINAL = "#30363d"

# ── Terminal / Log ───────────────────────────────────────────────────────────
TERMINAL_TEXT   = "#d1d1d1"
TERMINAL_DETAIL = "#7c8496"      # dim right-aligned detail (sizes, retry counts)
