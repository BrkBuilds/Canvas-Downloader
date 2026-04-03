"""Clean function boundary scanner."""
with open('sync_ui.py', 'rb') as f:
    raw = f.read()

# Normalize CR/LF
text = raw.decode('utf-8').replace('\r\n', '\n').replace('\r', '\n')
lines = text.split('\n')

keywords = [
    'def render_sync_step', 'def _render_filetype', 'def _render_ignored',
    'def _show_analysis_review', 'def _show_sync_confirmation',
    'def _run_analysis', 'def _run_sync', '@st.dialog',
    'def _saved_groups_hub', 'def _show_sync_cancelled',
    'def _show_sync_complete', 'def _show_sync_errors',
    'def _view_error_log', 'def _cleanup_sync',
    'def _render_sync_history', 'def _render_course_settings',
    'def _select_course_dialog', 'def _inject_hub',
    'def _hub_cleanup', 'def _reset_hub',
]

for i, line in enumerate(lines, 1):
    s = line.rstrip()
    for kw in keywords:
        if kw in s:
            print(f"{i}: {s[:100]}")
            break
