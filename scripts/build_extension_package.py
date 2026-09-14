"""Build the Chrome Web Store upload for `extension/`.

    python scripts/build_extension_package.py

Writes `installer_output/canvas-downloader-connector-<version>.zip`, which is
what gets uploaded to the Web Store's "Package" tab.

WHY THIS IS A SCRIPT AND NOT A ZIP COMMAND
------------------------------------------
Three things have to be true before the archive is worth uploading, and every
one of them has already been wrong in this repository at least once:

* **Every file the manifest NAMES has to exist.** A manifest referring to a
  missing icon does not degrade - Chrome refuses the whole extension with
  *"Manifest could not be loaded"*. That shipped once (`icon128.png`), and the
  product owner hit it before any test did.
* **Every script has to PARSE.** A syntax error makes the extension inert and
  Chrome reports it nowhere a student would look. Same shape as the icon.
* **`canvas-hosts.js` has to match `shared/institutions.py`.** It is generated,
  and a stale copy is the drift this repo keeps paying for.

A Web Store review cycle is measured in days, so a package that fails for one of
those reasons costs a week rather than a minute. All three are checked here, and
the build REFUSES rather than warns.

WHAT IS DELIBERATELY LEFT OUT
-----------------------------
`README.md` is for whoever works on this next, not for a student, and shipping
developer notes inside a reviewed package invites questions about files the
extension does not use. The archive carries exactly what `manifest.json` names,
plus the manifest.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXT = REPO / "extension"
OUT_DIR = REPO / "installer_output"


def _fail(msg: str) -> None:
    print(f"REFUSED: {msg}")
    raise SystemExit(1)


def manifest_files(manifest: dict) -> list[str]:
    """Every path the manifest names, in the order a reviewer would meet them.

    Mirrors `test_every_file_the_manifest_NAMES_actually_exists`, deliberately:
    the test proves the set is complete and this proves the archive carries it,
    and a second opinion about what the manifest references is how the two would
    come to disagree about which file was forgotten.
    """
    named: list[str] = []

    def add(value) -> None:
        if isinstance(value, str):
            named.append(value)
        elif isinstance(value, dict):
            for v in value.values():
                add(v)
        elif isinstance(value, list):
            for v in value:
                add(v)

    add(manifest.get("icons"))
    add((manifest.get("action") or {}).get("default_icon"))
    add((manifest.get("action") or {}).get("default_popup"))
    add((manifest.get("background") or {}).get("service_worker"))
    for cs in manifest.get("content_scripts") or []:
        add(cs.get("js"))
        add(cs.get("css"))
    for war in manifest.get("web_accessible_resources") or []:
        add(war.get("resources"))
    return named


def local_imports(js: Path) -> list[str]:
    """Relative ES-module imports, which the manifest never names.

    `popup.js` imports `canvas-hosts.js`, so the manifest's own list is NOT the
    whole package. Leaving it out produces an extension that loads and then
    fails on its first click, which is worse than one that refuses to load.
    """
    out: list[str] = []
    for line in js.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith(("import ", "export ")) or " from " not in line:
            continue
        spec = line.rsplit(" from ", 1)[1].strip().rstrip(";").strip("\"'")
        if spec.startswith("./") or spec.startswith("../"):
            out.append(spec.lstrip("./"))
    return out


def main() -> int:
    manifest_path = EXT / "manifest.json"
    if not manifest_path.exists():
        _fail(f"{manifest_path} does not exist")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    version = str(manifest.get("version") or "")
    if not version:
        _fail("the manifest carries no version")

    # 1. Everything the manifest names, plus what the popup imports.
    wanted = ["manifest.json"]
    for rel in manifest_files(manifest):
        if rel not in wanted:
            wanted.append(rel)
    popup = (manifest.get("action") or {}).get("default_popup")
    for js_name in [n for n in list(wanted) if n.endswith(".js")] + (
            [popup] if popup else []):
        p = EXT / js_name
        if js_name.endswith(".js") and p.exists():
            for dep in local_imports(p):
                if dep not in wanted:
                    wanted.append(dep)
    # popup.html's own <script src> - one level, the same depth the test walks.
    if popup and (EXT / popup).exists():
        html = (EXT / popup).read_text(encoding="utf-8")
        for chunk in html.split("<script")[1:]:
            if "src=" not in chunk.split(">")[0]:
                continue
            src = chunk.split("src=")[1]
            quote = src[0]
            src = src[1:].split(quote)[0]
            if not src.startswith(("http://", "https://", "//")):
                src = src.lstrip("./")
                if src not in wanted:
                    wanted.append(src)
                for dep in local_imports(EXT / src) if (EXT / src).exists() else []:
                    if dep not in wanted:
                        wanted.append(dep)

    missing = [n for n in wanted if not (EXT / n).exists()]
    if missing:
        _fail("the manifest names files that do not exist: " + ", ".join(missing))

    # 2. The generated host list must match the app's institution data.
    check = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "build_extension_hosts.py"), "--check"],
        capture_output=True, text=True, cwd=str(REPO))
    if check.returncode != 0:
        _fail("canvas-hosts.js is stale - run "
              "`python scripts/build_extension_hosts.py`\n" + check.stdout + check.stderr)

    # 3. Every script parses. Skipped rather than passed vacuously with no node,
    #    for the reason `test_every_extension_script_PARSES` states: a guard that
    #    cannot run is not a guard that passed.
    node = shutil.which("node")
    if node:
        for js_name in [n for n in wanted if n.endswith(".js")]:
            r = subprocess.run([node, "--check", str(EXT / js_name)],
                               capture_output=True, text=True)
            if r.returncode != 0:
                _fail(f"{js_name} does not parse:\n{r.stderr.strip()}")
        print(f"  parsed   {sum(1 for n in wanted if n.endswith('.js'))} script(s) with node")
    else:
        print("  SKIPPED  node is not on PATH, so the scripts were NOT parsed")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"canvas-downloader-connector-{version}.zip"
    if out.exists():
        out.unlink()
    # Deterministic order, and the files at the ROOT of the archive - the Web
    # Store rejects a zip whose manifest is one directory down.
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in sorted(wanted):
            z.write(EXT / rel, arcname=rel)

    print(f"  version  {version}")
    print(f"  files    {len(wanted)}: {', '.join(sorted(wanted))}")
    print(f"  written  {out}  ({out.stat().st_size:,} bytes)")
    print()
    print("Upload that zip at https://chrome.google.com/webstore/devconsole")
    print("The listing copy and every permission justification the review asks")
    print("for are in packaging/chrome-web-store/LISTING.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
