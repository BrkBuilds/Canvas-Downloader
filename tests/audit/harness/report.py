"""Render the run's findings as a self-contained HTML report.

Self-contained because a report that needs a web server or a CDN is a report
nobody opens six months later when the question "did this ever work?" comes up.
Everything - styles, data, the evidence excerpts - is inlined, so the file can be
mailed, archived or diffed against a previous run.

Findings are grouped by severity and each carries the ORACLE PAIR that produced
it. That is the part a reader needs first: "the review screen and the manifest
disagree" tells you where to look in a way that "sync bug" never does.
"""

from __future__ import annotations

import html
import json
import time
from pathlib import Path

from .findings import SEVERITIES, Ledger

SEV_COLOR = {
    "critical": ("#f87171", "rgba(248,113,113,.12)"),
    "high":     ("#fb923c", "rgba(251,146,60,.12)"),
    "medium":   ("#fbbf24", "rgba(251,191,36,.10)"),
    "low":      ("#60a5fa", "rgba(96,165,250,.10)"),
    "info":     ("#94a3b8", "rgba(148,163,184,.08)"),
}

ORACLE_NAMES = {
    "O1": "UI (what the app tells the user)",
    "O2": "Debug log (what the app says it did)",
    "O3": "Disk (what actually exists)",
    "O4": "Sync manifest (what the app believes)",
    "O5": "Canvas API (what should exist)",
}

CSS = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin:0; padding:32px; background:#0e1117; color:#e2e8f0;
  font:14px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }
.wrap { max-width:1100px; margin:0 auto; }
h1 { font-size:26px; margin:0 0 4px; color:#fff; letter-spacing:-.01em; }
h2 { font-size:17px; margin:34px 0 12px; color:#fff; }
.sub { color:#94a3b8; margin:0 0 24px; }
.tiles { display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr));
  gap:12px; margin-bottom:28px; }
.tile { background:#161b24; border:1px solid rgba(255,255,255,.08);
  border-radius:10px; padding:14px 16px; }
.tile .n { font-size:26px; font-weight:700; line-height:1.1; }
.tile .l { font-size:11px; text-transform:uppercase; letter-spacing:.07em;
  color:#94a3b8; margin-top:4px; }
table { width:100%; border-collapse:collapse; font-size:13px; }
th,td { text-align:left; padding:7px 10px; border-bottom:1px solid rgba(255,255,255,.06);
  vertical-align:top; }
th { color:#94a3b8; font-weight:600; font-size:11px; text-transform:uppercase;
  letter-spacing:.06em; }
.f { border:1px solid rgba(255,255,255,.08); border-left-width:3px;
  border-radius:8px; margin-bottom:10px; background:#141922; }
.f > summary { cursor:pointer; padding:11px 14px; list-style:none;
  display:flex; gap:10px; align-items:baseline; flex-wrap:wrap; }
.f > summary::-webkit-details-marker { display:none; }
.f[open] > summary { border-bottom:1px solid rgba(255,255,255,.06); }
.badge { font-size:10px; font-weight:700; text-transform:uppercase;
  letter-spacing:.06em; padding:2px 7px; border-radius:4px; white-space:nowrap; }
.title { font-weight:600; color:#fff; flex:1; min-width:260px; }
.meta { font-size:11px; color:#94a3b8; }
.body { padding:12px 14px 16px; }
.detail { color:#cbd5e1; margin-bottom:10px; white-space:pre-wrap; }
pre { background:#0b0e14; border:1px solid rgba(255,255,255,.06); border-radius:6px;
  padding:10px 12px; overflow-x:auto; font-size:12px; color:#cbd5e1; margin:0; }
code { background:rgba(255,255,255,.06); padding:1px 5px; border-radius:3px;
  font-size:12px; }
.oracle { display:inline-block; background:rgba(99,102,241,.14); color:#a5b4fc;
  border:1px solid rgba(99,102,241,.3); border-radius:4px; padding:1px 6px;
  font-size:10px; font-weight:600; margin-right:4px; }
.synthetic { background:rgba(168,85,247,.14); color:#d8b4fe;
  border:1px solid rgba(168,85,247,.3); border-radius:4px; padding:1px 6px;
  font-size:10px; }
.empty { padding:26px; text-align:center; color:#68d4a3;
  background:rgba(104,212,163,.08); border:1px solid rgba(104,212,163,.25);
  border-radius:10px; font-weight:600; }
.legend { font-size:12px; color:#94a3b8; margin:6px 0 18px; }
.legend b { color:#cbd5e1; }
@media (max-width:640px){ body{padding:16px;} .title{min-width:0;} }
"""


def build(rp, extra: dict | None = None) -> str:
    ledger = Ledger(rp.findings)
    rows = ledger.ranked()
    summary = ledger.summary()
    meta = rp.load_meta()
    extra = extra or {}

    parts = [f"<!doctype html><meta charset='utf-8'>"
             f"<title>Canvas Downloader live audit - {html.escape(rp.run_id)}</title>"
             f"<style>{CSS}</style><div class='wrap'>"]
    parts.append(f"<h1>Live audit report</h1>"
                 f"<p class='sub'>Run <code>{html.escape(rp.run_id)}</code> &middot; "
                 f"started {html.escape(str(meta.get('created', '?')))} &middot; "
                 f"rendered {time.strftime('%Y-%m-%d %H:%M')}</p>")

    # -- tiles ------------------------------------------------------------
    parts.append("<div class='tiles'>")
    parts.append(_tile(summary["defects"], "defects", "#fff"))
    for sev in SEVERITIES:
        n = summary["by_severity"].get(sev, 0)
        parts.append(_tile(n, sev, SEV_COLOR[sev][0] if n else "#475569"))
    parts.append("</div>")

    parts.append("<p class='legend'>Every finding is a disagreement between two "
                 "independent views of the same fact. "
                 + " ".join(f"<b>{k}</b> {html.escape(v)}."
                            for k, v in ORACLE_NAMES.items()) + "</p>")

    # -- scope ------------------------------------------------------------
    if extra.get("scope"):
        parts.append("<h2>What ran</h2><table><tr><th>Scenario</th><th>Course</th>"
                     "<th>Configuration</th><th>Result</th></tr>")
        for r in extra["scope"]:
            parts.append(
                f"<tr><td><code>{html.escape(str(r.get('name','')))}</code></td>"
                f"<td>{html.escape(str(r.get('course','')))}</td>"
                f"<td class='meta'>{html.escape(str(r.get('config',''))[:200])}</td>"
                f"<td>{html.escape(str(r.get('result','')))}</td></tr>")
        parts.append("</table>")

    if extra.get("coverage"):
        c = extra["coverage"]
        parts.append(
            "<h2>Combinatorial coverage</h2>"
            f"<p class='sub'>{c.get('runs','?')} runs cover "
            f"<b>{c.get('covered','?')} of {c.get('tuples','?')}</b> reachable "
            f"{c.get('strength','?')}-way factor combinations "
            f"({c.get('percent','?')}%). The full cross product of the "
            "configuration space is 2<sup>24</sup> = 16.7M runs; interaction "
            "coverage tests what actually breaks.</p>")

    # -- findings ---------------------------------------------------------
    parts.append("<h2>Findings</h2>")
    real = [r for r in rows if r.get("category") != "observation"]
    if not real:
        parts.append("<div class='empty'>No defects found. "
                     "Observations are listed below.</div>")
    for r in rows:
        parts.append(_finding(r))

    parts.append("</div>")
    out = "".join(parts)
    Path(rp.report).write_text(out, encoding="utf-8")
    return str(rp.report)


def _tile(n, label, color) -> str:
    return (f"<div class='tile'><div class='n' style='color:{color}'>{n}</div>"
            f"<div class='l'>{html.escape(label)}</div></div>")


def _finding(r: dict) -> str:
    sev = r.get("severity", "medium")
    fg, bg = SEV_COLOR.get(sev, SEV_COLOR["medium"])
    oracles = "".join(f"<span class='oracle' title='{html.escape(ORACLE_NAMES.get(o, o))}'>"
                      f"{html.escape(o)}</span>" for o in r.get("oracles", []))
    syn = "<span class='synthetic'>fixture</span>" if r.get("synthetic") else ""
    meta_bits = [b for b in (r.get("category"), r.get("scenario"), r.get("course"),
                             r.get("step")) if b]
    ev = r.get("evidence") or {}
    ev_html = ""
    if ev:
        ev_html = ("<pre>" + html.escape(json.dumps(ev, indent=2, ensure_ascii=False,
                                                    default=str)[:6000]) + "</pre>")
    return (
        f"<details class='f' style='border-left-color:{fg}; background:{bg}'>"
        f"<summary>"
        f"<span class='badge' style='background:{fg}22;color:{fg}'>{html.escape(sev)}</span>"
        f"<span class='title'>{html.escape(r.get('title', ''))}</span>"
        f"{oracles}{syn}"
        f"<span class='meta'>{html.escape(' · '.join(str(m) for m in meta_bits))}</span>"
        f"</summary><div class='body'>"
        + (f"<div class='detail'>{html.escape(r.get('detail', ''))}</div>"
           if r.get("detail") else "")
        + ev_html + "</div></details>")


def console(rp, limit: int = 30) -> dict:
    """Compact JSON digest for the agent - the report without the HTML."""
    ledger = Ledger(rp.findings)
    return {
        "summary": ledger.summary(),
        "top": [{k: v for k, v in r.items()
                 if k in ("severity", "category", "title", "oracles", "scenario",
                          "course", "synthetic")}
                for r in ledger.ranked(limit)],
        "report": str(rp.report),
    }
