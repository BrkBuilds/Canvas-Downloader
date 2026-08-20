"""Mutation pass for the conditional-stylesheet fixes.

Re-guards each stylesheet that was un-guarded, and re-nests the course list's
first-row offset, and asserts the tests go RED. See
``scripts/_mutate_tx_notice.py`` for why restore is snapshot-based rather than
``git checkout``, and why anchors are translated to the file's own newline.

    python scripts/_mutate_conditional_styles.py
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

AUTH = "ui/auth.py"
SELECTOR = "ui/course_selector.py"

TESTS = ["tests/test_conditional_stylesheets.py"]

#: (label, file, old, new)
CONDITIONAL_STYLE_MUTANTS = [
    ("the sidebar run-lock stylesheet is guarded again",
     AUTH,
     "    st.html(f\"\"\"<style>\n"
     "    /* No `opacity` here: global.css's single `button[disabled]` recipe",
     "    if _locked:\n"
     "      st.html(f\"\"\"<style>\n"
     "    /* No `opacity` here: global.css's single `button[disabled]` recipe"),

    ("the logout-lock stylesheet is guarded again",
     AUTH,
     "            st.html(\"\"\"<style>\n"
     "/* No `opacity`: global.css's single `button[disabled]` recipe paints this,",
     "            if _is_executing:\n"
     "             st.html(\"\"\"<style>\n"
     "/* No `opacity`: global.css's single `button[disabled]` recipe paints this,"),

    ("the active-nav stylesheet is guarded again",
     AUTH,
     "    active_key = f\"st-key-nav_btn_{mode}\"\n"
     "    st.html(f\"\"\"<style>",
     "    if mode in ['download', 'sync', 'panopto', 'today']:\n"
     "     active_key = f\"st-key-nav_btn_{mode}\"\n"
     "     st.html(f\"\"\"<style>"),

    ("a lock rule stops requiring :disabled, so it would paint at rest",
     AUTH,
     "    section[data-testid=\"stSidebar\"] div[class*=\"st-key-nav_btn_\"]"
     ":not([class*=\"logout\"]) button:disabled {{\n"
     "        cursor: not-allowed !important;",
     "    section[data-testid=\"stSidebar\"] div[class*=\"st-key-nav_btn_\"]"
     ":not([class*=\"logout\"]) button {{\n"
     "        cursor: not-allowed !important;"),

    ("the single-select stylesheet is guarded again",
     SELECTOR,
     '    st.html(f\'<style>{"".join(dynamic_css + boundary_css)}</style>\')',
     '    if dynamic_css:\n'
     '        st.html(f\'<style>{"".join(dynamic_css + boundary_css)}</style>\')'),

    # NOTE the anchors below carry a PRECEDING line each. The two renderers are
    # now textually identical from `boundary_css = []` onward - that is the
    # point of the fix - so an anchor starting there matches TWICE and
    # `replace(..., 1)` silently mutates the multi-select while the label says
    # single-select. That happened, and the mutant was reported as SURVIVED.
    ("the single-select first-row offset is re-nested inside a css guard",
     SELECTOR,
     "    # above it. Same defect, same shape, in the twin the fix did not reach.\n"
     "    boundary_css = []\n"
     "    if len(courses) > 0 and first_item_top_offset and first_item_top_offset != \"0\":",
     "    # above it. Same defect, same shape, in the twin the fix did not reach.\n"
     "    boundary_css = []\n"
     "    if dynamic_css:\n"
     "      if len(courses) > 0 and first_item_top_offset and first_item_top_offset != \"0\":"),

    ("the multi-select first-row offset is re-nested inside a css guard",
     SELECTOR,
     "            st.checkbox(base_name, key=chk_key)\n"
     "\n"
     "    boundary_css = []\n"
     "    if len(courses) > 0 and first_item_top_offset and first_item_top_offset != \"0\":",
     "            st.checkbox(base_name, key=chk_key)\n"
     "\n"
     "    boundary_css = []\n"
     "    if dynamic_css:\n"
     "      if len(courses) > 0 and first_item_top_offset and first_item_top_offset != \"0\":"),

    ("the multi-select twin regresses to its old guard",
     SELECTOR,
     '    st.html(f\'<style>{"".join(combined_css)}</style>\')',
     '    if combined_css:\n'
     '        st.html(f\'<style>{"".join(combined_css)}</style>\')'),

    ("one twin stops documenting why the emission is unconditional",
     SELECTOR,
     "    # Emitted UNCONDITIONALLY. A style-only st.html goes to the event container,",
     "    # Emitted always. A style-only st.html goes to the event container,"),
]

TEST_TARGET = TESTS


def _read(rel: str) -> str:
    return io.open(REPO / rel, encoding="utf-8", newline="").read()


def _write(rel: str, body: str) -> None:
    io.open(REPO / rel, "w", encoding="utf-8", newline="").write(body)


def _nl_of(body: str) -> str:
    return "\r\n" if "\r\n" in body else "\n"


def main() -> int:
    files = sorted({m[1] for m in CONDITIONAL_STYLE_MUTANTS})
    snapshot = {rel: _read(rel) for rel in files}

    stale = []
    for label, rel, old, _new in CONDITIONAL_STYLE_MUTANTS:
        if old.replace("\n", _nl_of(snapshot[rel])) not in snapshot[rel]:
            stale.append(f"{label!r} in {rel}")
    if stale:
        print("STALE ANCHORS - these mutants could not run, so any recorded "
              "score for them is UNMEASURED rather than passing:")
        for s in stale:
            print("  " + s)
        return 4

    if subprocess.run([sys.executable, "-m", "pytest", *TESTS, "-q"],
                      cwd=REPO).returncode != 0:
        print("BASELINE IS RED - fix that first")
        return 2

    caught, survived = [], []
    for label, rel, old, new in CONDITIONAL_STYLE_MUTANTS:
        current = _read(rel)
        if current != snapshot[rel]:
            print(f"\nABORT: {rel} changed underneath this pass. Nothing "
                  f"restored - what is on disk is that edit, not a mutant.")
            return 3
        nl = _nl_of(current)
        _write(rel, current.replace(old.replace("\n", nl),
                                    new.replace("\n", nl), 1))
        assert _read(rel) != snapshot[rel], f"{label}: mutation changed nothing"
        try:
            rc = subprocess.run([sys.executable, "-m", "pytest", *TEST_TARGET,
                                 "-q", "-x", "--no-header", "-p", "no:cacheprovider"],
                                cwd=REPO, capture_output=True).returncode
        finally:
            _write(rel, snapshot[rel])
        (caught if rc != 0 else survived).append(label)
        print(f"  [{'CAUGHT ' if rc != 0 else 'SURVIVED'}] {label}")

    print(f"\n{len(caught)}/{len(CONDITIONAL_STYLE_MUTANTS)} caught")
    for s in survived:
        print(f"  SURVIVED: {s}")
    return 0 if not survived else 1


if __name__ == "__main__":
    raise SystemExit(main())
