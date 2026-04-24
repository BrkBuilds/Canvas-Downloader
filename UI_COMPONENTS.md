# UI Components Framework

This document outlines the usage guidelines for shared UI components within the Canvas Downloader application. All shared components should be defined in `ui_shared.py` to maintain the "Physical Volume" aesthetic consistently across all screens.

## Help Explainer Card

The Help Explainer Card is a toggleable, non-intrusive help component. It defaults to a subtle "Help" button in the top right of its container. When clicked, it expands into a sleek dark-themed explainer card containing a title and informative text. 

### Best Practices & Guidelines
1. **Opt-in Information**: Only use this component for secondary or supplementary information that isn't strictly required to operate the screen. Do not use it for critical warnings or primary instructions.
2. **Concise Explanations**: Keep the text within the expanded card brief and straight to the point.
3. **Consistency**: The Help button itself is standardized. Do not attempt to override its color, icon, or alignment unless modifying the base component for the entire app.
4. **Unique Keys**: You must provide a highly unique `key_prefix` when calling this function. This prefix is injected into the CSS class names to ensure multiple help cards on the same screen do not conflict with each other's state or styling.

### Usage Example

```python
from ui_shared import render_help_card

# Basic implementation
render_help_card(
    key_prefix="sync_review",
    title="How to review your sync",
    text_html="Keep the files you want to download checked. If there are files you never want to sync, click their ignore icon to hide them permanently. Files you've edited locally are unchecked by default so your notes are never overwritten.",
    icon="💡" # Optional, defaults to "💡"
)
```

### Parameters

- `key_prefix` (str): **Required.** A unique identifier for the specific help card (e.g., `"sync_review"`, `"download_settings"`). Used to isolate Streamlit session state and CSS scopes.
- `title` (str): **Required.** The bolded header text inside the expanded card.
- `text_html` (str): **Required.** The body text of the explainer. Raw HTML is permitted (e.g., `<b>`, `<i>`, or inline links).
- `icon` (str): *Optional.* The emoji or character displayed next to the title in the expanded card. Defaults to `"💡"`.

