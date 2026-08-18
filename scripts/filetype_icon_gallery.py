"""Render every filetype icon for inspection, at the sizes it actually ships at.

Why a generator and not a hand-written page: the specimens are read out of
``shared/filetype_icons.py`` at build time, so the sheet can never show a set the
app no longer has. Re-run it after any change to that module.

    python scripts/filetype_icon_gallery.py

Writes two files next to each other in ``video/`` (untracked):

* ``filetype-icons.artifact.html`` - body content only, for the Artifact tool,
  which supplies its own doctype/head/body wrapper.
* ``filetype-icons.html`` - the same page wrapped as a valid standalone
  document. **The wrapper is not optional**: opened from disk without a doctype
  the browser falls into QUIRKS MODE and lays the page out differently from the
  artifact it is supposed to mirror.

The path-based glyphs are the ones ``tests/test_filetype_icons.py`` cannot bound
numerically (path data holds relative deltas), so this sheet is where they get
checked - which is the point of the 4x row.
"""

from __future__ import annotations

import os
import subprocess
import sys
from html import escape

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.filetype_icons import _FAMILIES, FILETYPE_SVG_DEFAULT, _mix  # noqa: E402

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "video")

# What each family is FOR, in the user's words rather than the code's.
BLURBS = {
    "pdf": "The one every course runs on. Red is doing most of the work here.",
    "doc": "Word documents. Same lines as a PDF, because both are text - the colour is what separates them.",
    "xls": "Spreadsheets. A header band over a 2x2 body reads as a table where drawn rules would blur.",
    "ppt": "Lecture decks. The bars are cut back out of the slide in the page colour.",
    "jpg": "Images. Sun over a ridge, no frame - the page already is the frame.",
    "mp4": "Video, including Panopto recordings kept as MP4.",
    "mp3": "Audio, including the extracted lecture audio track.",
    "zip": "Archives. Two teeth and a pull with a hole punched through it.",
    "url": "Shortcuts. The Panopto Link output lands here, as .url on Windows and .webloc on macOS.",
    "html": "Saved web pages. Almost every .html in a course folder is a Canvas page this app exported, and it opens in a browser - so it gets a globe, not a code mark.",
    "md": "Markdown - what the HTML converter produces. The M and its arrow are the Markdown mark.",
    "srt": "Subtitles from transcription. A screen with caption bars along its foot.",
    "txt": "Plain text, including transcripts and converted source files.",
    "py": "Source code. A shell prompt, so it can never be mistaken for markup.",
    "other": "The type we could not name. Faint on purpose: it must read as a file without claiming to know which kind.",
}

SURFACES = [
    ("#0e1117", "Page ground", "the app's base"),
    ("#1a1d27", "Card", "BG_DARK - the confirm dialog, folder cards"),
    ("#2d3248", "Raised card", "BG_CARD"),
    ("#0d1117", "Terminal", "BG_TERMINAL - the run log"),
]


def _old_icons() -> dict[str, str]:
    """The previous set, read out of git so the comparison cannot go stale."""
    import re

    try:
        src = subprocess.run(
            ["git", "show", "HEAD:shared/components.py"],
            capture_output=True, text=True, encoding="utf-8", check=True,
        ).stdout
    except Exception:
        return {}
    m = re.search(r"_FILETYPE_SVGS = \{(.*?)\n\}", src, re.S)
    if not m:
        return {}
    out = dict(re.findall(r"'([^']+)':\s*\"(data:image/svg\+xml,[^\"]+)\"", m.group(1)))
    d = re.search(r'_FILETYPE_SVG_DEFAULT = "(data:[^"]+)"', src)
    if d:
        out["(none)"] = d.group(1)
    return out


def build() -> str:
    families = []
    for colour, glyph, exts in _FAMILIES:
        key = exts[0]
        families.append({
            "key": key, "colour": colour, "tint": _mix(colour, 0.45),
            "glyph": glyph, "exts": list(exts),
            "blurb": BLURBS.get(key, ""),
        })

    # One CSS class per distinct icon, referenced by class everywhere else - the
    # sheet names 161 extensions and inlining a 480-byte URI at each would be
    # 77KB of duplicated string.
    icon_css = "\n".join(
        f'.i-{f["key"]}{{background-image:url("{f["colour"] and _icon_of(f)}")}}'
        for f in families
    )
    icon_css += f'\n.i-none{{background-image:url("{FILETYPE_SVG_DEFAULT}")}}'

    old = _old_icons()
    old_css = "\n".join(
        f'.o-{k}{{background-image:url("{v}")}}'
        for k, v in old.items() if k.isalnum() or k == "(none)"
    ).replace(".o-(none)", ".o-none")

    P = []
    P.append("<title>Filetype Icon Specimens</title>")
    P.append(f"<style>{_STYLE}\n{icon_css}\n{old_css}</style>")

    # --- Header -------------------------------------------------------------
    P.append('<header class="head">')
    P.append('<p class="eyebrow">Canvas Downloader &middot; shared/filetype_icons.py</p>')
    P.append("<h1>Filetype Icon Specimens</h1>")
    P.append(
        '<p class="lede">Fifteen icons covering '
        f'{sum(len(f["exts"]) for f in families)} extensions, each built from one page '
        "silhouette, one fold and a named glyph. The set they replace carried the "
        "extension as SVG <code>&lt;text&gt;</code> at 3.3&nbsp;CSS pixels, in the "
        "browser's fallback serif.</p>"
    )
    P.append('<p class="lede lede-2">This sheet is achromatic on purpose: the icons '
             "are the only colour on the page, so nothing competes with the judgement "
             "you are here to make.</p>")
    P.append("</header>")

    # --- 1. The size ladder -------------------------------------------------
    P.append(_section(
        "The size ladder",
        "16px is where these ship — the confirm dialog, the skipped-file panels, the "
        "synced-file rows. 18px is the error rows. Everything above is here so you can "
        "see what the mark is; everything at 16 is the actual judgement.",
    ))
    P.append('<div class="scroller"><table class="ladder">')
    P.append("<thead><tr><th>Family</th>"
             + "".join(f'<th><span class="px">{s}px</span></th>' for s in (16, 18, 24, 32, 64))
             + "<th></th></tr></thead><tbody>")
    for f in families:
        P.append(f'<tr><th scope="row"><span class="fam">{escape(f["key"])}</span></th>')
        for s in (16, 18, 24, 32, 64):
            P.append(f'<td><i class="ft i-{f["key"]}" style="width:{s}px;height:{s}px"></i></td>')
        P.append(f'<td class="glyphname">{escape(f["glyph"])}</td></tr>')
    P.append("</tbody></table></div>")

    # --- 2. Families --------------------------------------------------------
    P.append(_section(
        "The fifteen families",
        "Colour carries recognition first — red is a PDF, green is a spreadsheet — and "
        "the glyph disambiguates within a colour. Extensions are listed in full: every "
        "one of them resolves to the icon shown, with no fallback.",
    ))
    P.append('<div class="fams">')
    for f in families:
        P.append('<article class="fam-card">')
        P.append(f'<div class="fam-top"><i class="ft i-{f["key"]}" style="width:56px;height:56px"></i>')
        P.append('<div class="fam-meta">')
        P.append(f'<h3>{escape(f["glyph"])}</h3>')
        P.append(f'<p class="swatches">'
                 f'<span class="sw" style="background:{f["colour"]}"></span>'
                 f'<code>{f["colour"]}</code>'
                 f'<span class="sw sw-t" style="background:{f["tint"]}"></span>'
                 f'<code class="dim">{f["tint"]} fold</code></p>')
        P.append("</div></div>")
        if f["blurb"]:
            P.append(f'<p class="blurb">{escape(f["blurb"])}</p>')
        P.append('<p class="exts">'
                 + " ".join(f"<code>.{escape(e)}</code>" for e in f["exts"])
                 + "</p>")
        P.append("</article>")
    P.append("</div>")

    # --- 3. On every surface ------------------------------------------------
    P.append(_section(
        "On every surface they land on",
        "These are the four grounds the app actually paints behind an icon. A mark that "
        "holds on the page but disappears in the terminal log is not finished.",
    ))
    P.append('<div class="scroller"><div class="surfaces">')
    for bg, name, note in SURFACES:
        P.append(f'<div class="surf" style="background:{bg}">')
        P.append(f'<p class="surf-name">{escape(name)}<span class="dim"> {escape(note)}</span></p>')
        P.append('<div class="surf-row">'
                 + "".join(f'<i class="ft i-{f["key"]}" style="width:16px;height:16px"></i>'
                           for f in families)
                 + "</div>")
        P.append('<div class="surf-row">'
                 + "".join(f'<i class="ft i-{f["key"]}" style="width:32px;height:32px"></i>'
                           for f in families)
                 + "</div>")
        P.append("</div>")
    P.append("</div></div>")

    # --- 4. In context ------------------------------------------------------
    P.append(_section(
        "In context",
        "The Confirm Sync file list, rebuilt with the app's own row markup. Note the "
        "EXT badge beside each icon: the extension was never lost when the label came "
        "off the page, it just moved somewhere it can be read.",
    ))
    rows = [
        ("pdf", "TLS med Wireshark", "PDF", "1.3 MB"),
        ("ppt", "Forelaesning 7 - Transportlaget", "PPTX", "14.8 MB"),
        ("xls", "Karakterfordeling 2026", "XLSX", "88 KB"),
        ("mp4", "Panopto - Uge 7 optagelse", "MP4", "412 MB"),
        ("mp3", "Panopto - Uge 7 lydspor", "MP3", "38 MB"),
        ("srt", "Panopto - Uge 7 undertekster", "SRT", "16 KB"),
        ("url", "Link til optagelse", "URL", ""),
        ("md", "Ugeplan", "MD", "6 KB"),
        ("py", "Create_ILearn_tables", "SQL", "3 KB"),
        ("zip", "Oevelser uge 1-7", "ZIP", "62 MB"),
        ("none", "Datafil uden kendt type", "DAT", "2 KB"),
    ]
    P.append('<div class="ctx"><ul class="filelist">')
    for key, name, badge, size in rows:
        P.append(f'<li><i class="ft i-{key}"></i><span class="li-text">{escape(name)}</span>'
                 f'<span class="li-ext">{escape(badge)}</span>'
                 + (f'<span class="li-size">{escape(size)}</span>' if size else "")
                 + "</li>")
    P.append("</ul></div>")

    P.append('<p class="capt">And the filetype pills, as the completion screen builds them:</p>')
    P.append('<div class="ctx"><div class="pills">')
    for key, label, count in [("pdf", "PDF", 56), ("ppt", "PPTX", 51), ("mp4", "MP4", 12),
                              ("md", "MD", 8), ("none", "Other files", 4)]:
        P.append(f'<div class="pill"><i class="ft i-{key}"></i>'
                 f'<span class="pill-l">{escape(label)}</span>'
                 f'<span class="pill-c">{count}</span></div>')
    P.append("</div></div>")

    # --- 5. Before / after --------------------------------------------------
    if old:
        P.append(_section(
            "What they replace",
            "Read at 16px, left to right. The old label is not small — it is absent: at "
            "the size it renders, a 5-unit glyph in a 24-unit viewBox is 3.3 CSS pixels.",
        ))
        P.append('<div class="scroller"><table class="ba"><thead><tr>'
                 "<th>Extension</th><th>Before 16px</th><th>After 16px</th>"
                 "<th>Before 64px</th><th>After 64px</th></tr></thead><tbody>")
        pairs = [("pdf", "pdf"), ("pptx", "ppt"), ("docx", "doc"), ("xlsx", "xls"),
                 ("zip", "zip"), ("html", "html"), ("mp4", "mp4"), ("mp3", "mp3"),
                 ("jpg", "jpg"), ("txt", "txt"), ("url", "url"), ("none", "none")]
        for o, n in pairs:
            if o not in old and o != "none":
                continue
            P.append(f'<tr><th scope="row"><span class="fam">{escape(o)}</span></th>')
            P.append(f'<td><i class="ft o-{o}" style="width:16px;height:16px"></i></td>')
            P.append(f'<td><i class="ft i-{n}" style="width:16px;height:16px"></i></td>')
            P.append(f'<td><i class="ft o-{o}" style="width:64px;height:64px"></i></td>')
            P.append(f'<td><i class="ft i-{n}" style="width:64px;height:64px"></i></td></tr>')
        P.append("</tbody></table></div>")

        P.append(_section(
            "And the ones that had nothing",
            "Ten extensions the old pill whitelist named itself had no icon in the table "
            "behind it, so they rendered as a blank grey page beside a label naming the "
            "type. So did two of this app's own outputs.",
        ))
        P.append('<div class="scroller"><table class="ba"><thead><tr>'
                 "<th>Extension</th><th>Before</th><th>After</th><th>Why it reaches the UI</th>"
                 "</tr></thead><tbody>")
        gaps = [
            ("md", "md", "The HTML converter writes it"),
            ("srt", "srt", "Panopto subtitles - in the Confirm Sync dialog"),
            ("webloc", "url", "The macOS Shortcut output"),
            ("pptm", "ppt", "Admitted by the Slides &amp; PDFs filter"),
            ("potx", "ppt", "Admitted by the Slides &amp; PDFs filter"),
            ("py", "py", "Named by the pill whitelist"),
            ("sql", "py", "Named by the pill whitelist"),
            ("json", "py", "Named by the pill whitelist"),
            ("css", "py", "Named by the pill whitelist"),
            ("java", "py", "Named by the pill whitelist"),
        ]
        for ext, n, why in gaps:
            P.append(f'<tr><th scope="row"><span class="fam">.{escape(ext)}</span></th>')
            P.append('<td><i class="ft o-none" style="width:22px;height:22px"></i></td>')
            P.append(f'<td><i class="ft i-{n}" style="width:22px;height:22px"></i></td>')
            P.append(f'<td class="why">{why}</td></tr>')
        P.append("</tbody></table></div>")

    # --- 6. Index -----------------------------------------------------------
    P.append(_section(
        "Every extension",
        "The full table, so you can check a type you expect to see rather than take the "
        "count on trust.",
    ))
    P.append('<div class="index">')
    for f in families:
        for e in f["exts"]:
            P.append(f'<span class="ix"><i class="ft i-{f["key"]}"></i><code>.{escape(e)}</code></span>')
    P.append("</div>")

    P.append('<footer class="foot"><p>Generated from '
             "<code>shared/filetype_icons.py</code> by "
             "<code>scripts/filetype_icon_gallery.py</code>. Re-run it after any change "
             "to the set.</p></footer>")

    return "\n".join(P)


def _icon_of(f) -> str:
    from shared.filetype_icons import FILETYPE_SVGS
    return FILETYPE_SVGS[f["exts"][0]]


def _section(title: str, note: str) -> str:
    return (f'<section class="sec"><h2>{escape(title)}</h2>'
            f'<p class="note">{note}</p></section>')


_STYLE = """
*,*::before,*::after{box-sizing:border-box}
:root{
  --ground:#f4f5f7; --surface:#ffffff; --sunken:#eceef2;
  --ink:#12151d; --ink-2:#3d4453; --muted:#697384; --line:#dde1e8;
  --accent:#3f5f7d; --rule:#c9cfd9;
  --mono:ui-monospace,"Cascadia Mono","SF Mono",Menlo,Consolas,monospace;
  --sans:ui-sans-serif,"Segoe UI Variable Text","Segoe UI","SF Pro Text",system-ui,sans-serif;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --ground:#0f1115; --surface:#171a21; --sunken:#12151b;
  --ink:#e4e8ef; --ink-2:#b7bfcc; --muted:#828b9b; --line:#272c36;
  --accent:#8fb4d4; --rule:#333a46;
}}
:root[data-theme="dark"]{
  --ground:#0f1115; --surface:#171a21; --sunken:#12151b;
  --ink:#e4e8ef; --ink-2:#b7bfcc; --muted:#828b9b; --line:#272c36;
  --accent:#8fb4d4; --rule:#333a46;
}
body{margin:0;background:var(--ground);color:var(--ink);font-family:var(--sans);
  font-size:15px;line-height:1.6;-webkit-font-smoothing:antialiased;
  padding:clamp(20px,5vw,64px) clamp(16px,5vw,56px) 72px}
.head,.sec,.fams,.ctx,.index,.foot,.scroller,.capt{max-width:1080px;margin-inline:auto}
.eyebrow{font-family:var(--mono);font-size:11.5px;letter-spacing:.09em;
  text-transform:uppercase;color:var(--muted);margin:0 0 14px}
h1{font-size:clamp(30px,5vw,44px);line-height:1.06;letter-spacing:-.025em;
  font-weight:640;margin:0 0 18px;text-wrap:balance}
.lede{font-size:17px;color:var(--ink-2);max-width:62ch;margin:0 0 10px}
.lede-2{font-size:15px;color:var(--muted)}
.head{padding-bottom:34px;border-bottom:1px solid var(--rule);margin-bottom:38px}
.sec{margin:60px auto 20px}
.sec h2{font-size:12px;font-family:var(--mono);letter-spacing:.1em;text-transform:uppercase;
  color:var(--accent);font-weight:600;margin:0 0 10px;
  padding-bottom:9px;border-bottom:1px solid var(--line)}
.note{font-size:14.5px;color:var(--muted);max-width:66ch;margin:0}
code{font-family:var(--mono);font-size:.86em}
.dim{color:var(--muted)}
.scroller{overflow-x:auto}
.ft{display:inline-block;vertical-align:middle;flex:0 0 auto;
  width:16px;height:16px;background-repeat:no-repeat;background-size:contain;
  background-position:center}

/* --- ladder --- */
.ladder{border-collapse:collapse;font-size:13px;min-width:560px}
.ladder th,.ladder td{padding:9px 16px;text-align:center;border-bottom:1px solid var(--line)}
.ladder thead th{color:var(--muted);font-weight:500;font-size:11px;
  border-bottom:1px solid var(--rule)}
.ladder tbody tr:hover{background:var(--surface)}
.ladder th[scope="row"]{text-align:left;padding-left:0}
.px{font-family:var(--mono);letter-spacing:.03em}
.fam{font-family:var(--mono);font-size:12.5px;color:var(--ink-2)}
.glyphname{font-family:var(--mono);font-size:11.5px;color:var(--muted);text-align:right}

/* --- families --- */
.fams{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px}
.fam-card{background:var(--surface);border:1px solid var(--line);border-radius:10px;
  padding:18px 18px 16px;display:flex;flex-direction:column;gap:11px}
.fam-top{display:flex;gap:15px;align-items:center}
.fam-meta h3{margin:0 0 5px;font-size:15px;font-weight:600;font-family:var(--mono);
  letter-spacing:-.01em}
.swatches{margin:0;display:flex;align-items:center;gap:6px;font-size:11px;flex-wrap:wrap}
.sw{width:11px;height:11px;border-radius:3px;flex:0 0 auto;
  box-shadow:inset 0 0 0 1px rgba(128,128,128,.35)}
.blurb{margin:0;font-size:13.5px;color:var(--ink-2)}
.exts{margin:0;display:flex;flex-wrap:wrap;gap:4px 5px}
.exts code{background:var(--sunken);border-radius:4px;padding:1px 5px;
  font-size:11px;color:var(--muted)}

/* --- surfaces --- */
.surfaces{display:flex;gap:12px;min-width:640px}
.surf{flex:1;border-radius:10px;padding:14px 16px 16px;border:1px solid var(--line)}
.surf-name{margin:0 0 12px;font-size:11px;font-family:var(--mono);color:#c7ccd9;
  letter-spacing:.03em}
.surf-name .dim{color:#7b8496}
.surf-row{display:flex;gap:9px;flex-wrap:wrap;align-items:center;margin-bottom:10px}
.surf-row:last-child{margin-bottom:0}

/* --- in context: the app's own row markup --- */
.ctx{background:#1a1d27;border:1px solid #2d3248;border-radius:12px;
  padding:16px 18px;margin-top:18px}
.filelist{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:3px}
.filelist li{display:flex;align-items:center;gap:9px;padding:7px 10px;border-radius:7px;
  background:rgba(255,255,255,.03)}
.li-text{color:#f1f5f9;font-size:13.5px;flex:1;min-width:0;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
.li-ext{font-size:10px;font-weight:700;letter-spacing:.4px;color:#bababa;
  background:rgba(255,255,255,.08);border-radius:3px;padding:2px 6px;flex:0 0 auto;
  font-family:var(--mono)}
.li-size{font-size:11.5px;color:#8b949e;flex:0 0 auto;font-variant-numeric:tabular-nums}
.capt{margin:26px auto 0;font-size:13.5px;color:var(--muted)}
.pills{display:flex;flex-wrap:wrap;gap:9px}
.pill{display:flex;align-items:center;gap:7px;background:rgba(255,255,255,.05);
  border:1px solid rgba(255,255,255,.08);border-radius:20px;padding:5px 13px 5px 10px}
.pill-l{font-size:11.5px;color:#e2e8f0;letter-spacing:.02em}
.pill-c{font-size:11.5px;color:#8b949e;font-variant-numeric:tabular-nums}

/* --- before / after --- */
.ba{border-collapse:collapse;font-size:13px;min-width:520px;width:100%}
.ba th,.ba td{padding:10px 14px;border-bottom:1px solid var(--line);text-align:center}
.ba thead th{color:var(--muted);font-weight:500;font-size:11px;
  border-bottom:1px solid var(--rule)}
.ba th[scope="row"]{text-align:left;padding-left:0}
.ba td:not(.why){background:#12151b}
.why{text-align:left;color:var(--muted);font-size:12.5px}

/* --- index --- */
.index{display:flex;flex-wrap:wrap;gap:5px 6px}
.ix{display:inline-flex;align-items:center;gap:6px;background:var(--surface);
  border:1px solid var(--line);border-radius:6px;padding:4px 9px 4px 7px}
.ix code{font-size:11px;color:var(--ink-2)}

.foot{margin-top:64px;padding-top:22px;border-top:1px solid var(--rule)}
.foot p{margin:0;font-size:12.5px;color:var(--muted)}
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
"""

_WRAPPER = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{head}
</head>
<body>
{body}
</body>
</html>
"""


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    page = build()

    artifact_path = os.path.join(OUT_DIR, "filetype-icons.artifact.html")
    with open(artifact_path, "w", encoding="utf-8") as fh:
        fh.write(page)

    # The standalone twin. Title and style move into <head>; without the doctype
    # a file:// open renders in quirks mode, i.e. not the page that was reviewed.
    lines = page.split("\n")
    head = "\n".join(lines[:2])
    body = "\n".join(lines[2:])
    standalone = os.path.join(OUT_DIR, "filetype-icons.html")
    with open(standalone, "w", encoding="utf-8") as fh:
        fh.write(_WRAPPER.format(head=head, body=body))

    for p in (artifact_path, standalone):
        print(f"{os.path.getsize(p) / 1024:7.1f} KB  {p}")


if __name__ == "__main__":
    main()
