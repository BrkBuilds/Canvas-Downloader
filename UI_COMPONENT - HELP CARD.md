# UI Components Framework

This document outlines the usage guidelines for shared UI components within the Canvas Downloader application. All shared components should be defined in `ui_shared.py` to maintain the "Physical Volume" aesthetic consistently across all screens.

## Help Explainer Card

The Help Explainer Card is a toggleable, non-intrusive help component. It supports both integrated rendering and "split rendering" (where the trigger button is separated from the content card).

### Key Features
- **Persistent Toggle**: The trigger button (icon + "Help" text) remains visible even when the card is expanded, acting as a toggle.
- **Split Rendering**: Using the `mode` parameter, you can place the Help trigger in a header while the expanded card appears elsewhere (e.g., above or below specific content blocks).

### Best Practices & Guidelines
1. **Opt-in Information**: Only use for secondary or supplementary info.
2. **Concise Explanations**: Keep text brief and focused.
3. **Unique Keys**: Provide a unique `key_prefix` to isolate state and CSS.
4. **Header Alignment ("Snug" Mode)**: When placing the help tag next to a header, use the "Flex Row Hack" to override Streamlit's rigid column gaps. See example below.

### Usage Examples

#### 1. Integrated (Default)
```python
from ui_shared import render_help_card

render_help_card(
    key_prefix="simple_help",
    title="Basic Guide",
    text_html="This card and its button render together."
)
```

#### 2. Split Rendering (Snug Header)
To place a help tag perfectly snug against a header:
```python
# 1. Render the Trigger in the header row
st.html("""<style>
    div.st-key-header_row [data-testid="stHorizontalBlock"] {
        display: flex !important; gap: 4px !important; align-items: center !important;
    }
    div.st-key-header_row [data-testid="column"] { width: auto !important; flex: 0 0 auto !important; }
    div.st-key-my_help_btn { margin-top: 20px !important; } /* Adjust for H2 baseline */
</style>""")

with st.container(key="header_row"):
    c1, c2 = st.columns([1, 10])
    with c1: st.markdown("## My Header")
    with c2: render_help_card(..., mode="button", key_prefix="my")

# 2. Render the Card content elsewhere
render_help_card(..., mode="card", key_prefix="my")
```

### Parameters

- `key_prefix` (str): **Required.** Unique identifier for state and CSS isolation.
- `title` (str): **Required.** Header text inside the card.
- `text_html` (str): **Required.** Body content.
- `icon` (str): *Optional.* Emoji/icon for the expanded card title.
- `mode` (str): *Optional.* 
    - `"auto"` (default): Renders both button and card together.
    - `"button"`: Renders only the trigger button (persistent toggle).
    - `"card"`: Renders only the expanded content (if state is True).

