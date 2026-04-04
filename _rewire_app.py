"""
Phase 6/7: Rewire app.py to delegate to extracted ui/ modules.

Replaces:
  - Sidebar (L160-521) -> ui.auth.render_sidebar()
  - Presets (L540-786) -> ui.presets delegation
  - Step 1 course select (L796-1018) -> ui.course_selector.render_course_selector()
  - Step 2 settings (L1022-2428) -> ui.download_settings.render_download_settings()
"""

with open('app.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

print(f"Original: {len(lines)} lines")

# Build replacement map: (start_idx, end_idx) -> replacement_lines
# All indices are 0-based

# 1. Sidebar: L160-521 (indices 159-520) -> 3-line delegation
sidebar_replacement = [
    "# --- Sidebar: Authentication (delegated to ui.auth) ---\r\n",
    "with st.sidebar:\r\n",
    "    from ui.auth import render_sidebar\r\n",
    "    render_sidebar(fetch_courses)\r\n",
    "\r\n",
]

# 2. Auth-gate + Main container opening: L524-537 stay as-is (they're structural)
# The auth-gate (L524-526) and container opening (L528-536) remain untouched.

# 3. Presets (L540-786) -> delegation import + pass-through buttons
# These are inside `with _main_content.container():` so they stay at that nesting level
preset_replacement = [
    "\r\n",
    "    # ===================================================================\r\n",
    "    # Preset Dialogs (delegated to ui.presets)\r\n",
    "    # ===================================================================\r\n",
    "    from ui.presets import _save_config_dialog, _presets_hub_dialog\r\n",
    "\r\n",
]

# 4. Step 1 Download course selection: L796-1018 -> delegation
# Original line 796 is `        else:` (inside step==1 block)
# Lines 797-1018 are the body under that else
# Replace L797-1018 with delegation
step1_replacement = [
    "            from ui.course_selector import render_course_selector\r\n",
    "            render_course_selector(fetch_courses)\r\n",
    "\r\n",
]

# 5. Step 2: L1022-2428 -> delegation
# L1021 is `    elif st.session_state['step'] == 2:` — KEEP this
# L1022-2428 is the body -> replace with delegation
step2_replacement = [
    "        from ui.download_settings import render_download_settings\r\n",
    "        render_download_settings(fetch_courses)\r\n",
    "\r\n",
]

# Apply replacements from bottom to top to preserve line indices
new_lines = list(lines)

# Step 2: Replace L1022-2428 (indices 1021-2427) — but keep L1021 (the elif)
new_lines[1021:2428] = step2_replacement

# Step 1: Replace L797-1018 (indices 796-1017) — keep L796 (`else:`)
new_lines[796:1018] = step1_replacement

# Presets: Replace L540-786 (indices 539-785)
new_lines[539:786] = preset_replacement

# Sidebar: Replace L160-521 (indices 159-520)
# We keep line 522-523 (blank lines before auth gate)
new_lines[159:521] = sidebar_replacement

with open('app.py', 'w', encoding='utf-8', newline='') as f:
    f.writelines(new_lines)

print(f"After rewiring: {len(new_lines)} lines")
print("Done! app.py has been rewired to delegate to ui/ modules.")
