# UI Dialog Fixes - Summary Report

## Issues Fixed

### 1. **Button Styling Bug (Issue 1.1)** ✅
**Problem**: Segmented control buttons in dialogs show wrong inactive state styling. On hover, they briefly show correct styling.

**Root Cause**: In dialog portals, Streamlit's own button CSS loads after ours and wins at equal specificity `(0,1,2)`. The `:hover` pseudo-class increases our specificity to `(0,2,2)`, which beats Streamlit's rule—explaining why hover looked correct but the default state didn't.

**Solution**: Modified `render_favorites_pill()` to prefix all button CSS selectors with `div[role="dialog"]` when `in_dialog=True` (via variable `_bp`). This boosts specificity to `(0,2,*)` so our CSS always wins.

**Files Modified**:
- `ui/course_selector.py` lines 114-196: Added `_bp` prefix variable, applied to all button selectors

---

### 2. **Vertical Spacing Issues (Issues 1.2 & 2)** ✅
**Problem**: Both dialogs have excessive dead space due to ghost-box margins from `st.markdown()`:
- **Sync dialog**: Large gap between dialog title ("Select Course to sync") and "Show:" label
- **Hub dialog**: Large gaps between "← Back to Edit" → "Select Course" → "Show:" → separator

**Root Cause**: `st.markdown()` wraps content in `stMarkdownContainer` with a **1rem bottom ghost margin** (per CLAUDE.md). CSS-injection `<style>` blocks also create ghost boxes. Additionally, dialog portal context may not apply the global.css collapse rule effectively.

**Solution**: 
1. **Eliminated ghost margins** by switching to `st.html()`:
   - "Show:" label (course_selector.py)
   - h3 "Select Course" (hub_dialog.py)
   - All `<hr>` separators (both dialogs)

2. **Added ghost-box collapse CSS** scoped to `div[role="dialog"]` as belt-and-suspenders backup.

3. **Reduced dialog body top padding** via targeted CSS on `stDialogScrollableBody`.

4. **Tightened gap compression** to reduce inter-element spacing.

**Files Modified**:
- `ui/course_selector.py` lines 206-213: Changed "Show:" to `st.html()`
- `ui/course_selector.py` line 115: Adjusted `_label_margin_top: "0px"`, `_label_margin_bottom: "4px"`, `_seg_margin_top: "2px"`
- `ui/sync_dialogs.py` lines 440-475: Added ghost-box collapse + dialog padding reduction CSS; switched 2× `hr` to `st.html()`; increased scroll container heights (55vh→58vh, 45vh→48vh)
- `ui/hub_dialog.py` lines 874-927: Switched h3 to `st.html()`; added ghost-box collapse + dialog padding CSS; tightened gap to 0.25rem; increased scroll container to 480px

---

## CSS Changes Summary

### course_selector.py
```python
# NEW: Specificity prefix for dialog button CSS
_bp = 'div[role="dialog"] ' if in_dialog else ''

# CHANGED: Show: label uses st.html() (not st.markdown)
# OLD: st.markdown("<p>Show:</p>", ...)
# NEW: st.html("<p>Show:</p>")

# CHANGED: Adjusted margins for dialog mode
# _label_margin_top: "4px" → "0px"
# _label_margin_bottom: "12px" → "4px"
# _seg_margin_top: "-10px" → "2px"
```

### sync_dialogs.py
```css
/* NEW: Belt-and-suspenders ghost-box collapse for dialog portal */
div[role="dialog"] div[data-testid="element-container"]:has(> div[data-testid="stMarkdownContainer"] > style),
div[role="dialog"] div[data-testid="element-container"]:has(> div[data-testid="stMarkdownContainer"]:empty) {
    display: none !important; height: 0 !important; margin: 0 !important; padding: 0 !important;
}

/* NEW: Reduce dialog body top padding */
div[role="dialog"] [data-testid="stDialogScrollableBody"] {
    padding-top: 0.25rem !important;
}

/* CHANGED: All <hr> from st.markdown() to st.html() */
/* Increased scroll container heights to use recovered space: 55vh→58vh, 45vh→48vh */
```

### hub_dialog.py
```python
# CHANGED: h3 from st.markdown() to st.html()
# OLD: st.markdown("<h3>Select Course</h3>", unsafe_allow_html=True)
# NEW: st.html("<h3>Select Course</h3>")

# CHANGED: Adjusted h3 margin-top: -8px → -4px (works better with zero ghost-box margin)

# CHANGED: All <hr> from st.markdown() to st.html()

# CHANGED: Tightened gap compression: 0.35rem → 0.25rem
```

```css
/* NEW: Ghost-box collapse CSS (scoped to course selector layer) */
div[role="dialog"] div[data-testid="element-container"]:has(> div[data-testid="stMarkdownContainer"] > style),
div[role="dialog"] div[data-testid="element-container"]:has(> div[data-testid="stMarkdownContainer"]:empty) {
    display: none !important; height: 0 !important; margin: 0 !important; padding: 0 !important;
}

/* NEW: Reduce dialog body top padding */
div[role="dialog"] [data-testid="stDialogScrollableBody"] {
    padding-top: 0.25rem !important;
}

/* CHANGED: Increased scroll container height to 480px (from 460px) to use recovered space */
```

---

## Verification

- ✅ All files compile successfully (no Python syntax errors)
- ✅ Code changes applied to all 3 affected files
- ✅ Button prefix specificity fix: `_bp` variable correctly applied to all button CSS selectors when `in_dialog=True`
- ✅ Ghost-box elimination: "Show:" label, h3, and hr elements switched to `st.html()`
- ✅ Dialog CSS rules added for ghost-box collapse and padding reduction
- ✅ Scroll container heights increased to use recovered vertical space
- ✅ Gap compression values tightened for more compact dialog layout

---

## Testing Recommended

To verify the fixes work as intended:

1. **Test Sync Dialog ("Select Course to sync")**:
   - Check spacing between dialog title and "Show:" label (should be tight, minimal gap)
   - Verify segmented control buttons (inactive/hover/active states) match Download mode
   - Confirm course list has good height and visibility
   - Verify "Confirm Selection" button has breathing room at bottom

2. **Test Hub Dialog ("Saved Groups & Pairs", course selector layer)**:
   - Check spacing: "← Back to Edit" → "Select Course" → "Show:" (should be tight)
   - Verify segmented control button states
   - Confirm separator margins are minimal
   - Verify course list uses recovered vertical space

3. **Visual Comparison**:
   - Compare with Download mode for consistent button styling
   - Check that no spacing is too cramped (minimum 4-6px visual gaps)
   - Verify all elements render crisply without overlaps

---

## CLAUDE.md Compliance

All changes follow CLAUDE.md guidelines:
- ✅ Eliminated use of `st.markdown()` for non-CSS content (used `st.html()` instead)
- ✅ Used `st.html()` for HTML-only injections (zero-footprint, no ghost-box margins)
- ✅ CSS injection still uses `st.markdown()` where necessary (Streamlit's st.html iframe may not support CSS escape)
- ✅ Scoped CSS rules with `div[role="dialog"]` to prevent global leakage
- ✅ Used `:has()` guards for layer-specific rules (self-deactivate on other layers)
- ✅ Avoided `:has() + ~` sibling combinators on main-app components

---

## Files Changed
1. `ui/course_selector.py` — Button CSS prefix fix + Show: label st.html() conversion
2. `ui/sync_dialogs.py` — Ghost-box collapse + dialog padding + hr st.html() conversion
3. `ui/hub_dialog.py` — h3 st.html() conversion + ghost-box collapse + dialog padding + tighter gaps
