"""
build_msix.py - SEPARATE Microsoft Store (MSIX) packaging track for Canvas Downloader.

This is a supplement to the main Inno Setup .exe installer, NOT a replacement.
It does not touch build_windows.py, Canvas_Downloader_Setup.iss, or the dist/
folder contents in any way. It reuses the existing PyInstaller output read-only
(via a makeappx mapping file) and produces a .msix for upload to Partner Center.

--------------------------------------------------------------------------------
USAGE
--------------------------------------------------------------------------------
  1. Build the app first (produces dist/Canvas Downloader/):
         python build_windows.py --no-installer
     (or a full `python build_windows.py` - either way dist/ is reused as-is)

  2. Build the Store package:
         python build_msix.py
     -> msix_output/CanvasDownloader_<ver>.msix   (unsigned; the Store signs it)

  3. (Optional) Build + self-sign + sideload-install for local testing in the
     MSIX container BEFORE submitting:
         python build_msix.py --test

Flags:
  --test         Self-sign with a generated dev cert and print sideload steps.
  --dist PATH    Override the PyInstaller output folder (default: dist/Canvas Downloader).
  --no-pack      Generate manifest + logos + mapping file only; skip makeappx.

Prerequisites: Windows SDK (provides makeappx.exe + signtool.exe). Install via:
    winget install Microsoft.WindowsSDK.10.0.26100
Identity values come from Partner Center -> see msix/README.md and msix/identity.json.
--------------------------------------------------------------------------------
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).parent.resolve()
MSIX_DIR = ROOT / "msix"
BUILD_DIR = MSIX_DIR / "build"
ASSETS_OUT = BUILD_DIR / "Assets"
OUTPUT_DIR = ROOT / "msix_output"
TEMPLATE = MSIX_DIR / "AppxManifest.template.xml"
IDENTITY_JSON = MSIX_DIR / "identity.json"
SOURCE_ICON = ROOT / "assets" / "icon.png"

PLACEHOLDER_PREFIX = "__REPLACE"

# (filename, (width, height), mode) - "square" resizes; "fit" centers on transparent canvas.
LOGO_SPECS = [
    ("StoreLogo.png",        (50, 50),    "square"),
    ("Square44x44Logo.png",  (44, 44),    "square"),
    ("Square71x71Logo.png",  (71, 71),    "square"),
    ("Square150x150Logo.png",(150, 150),  "square"),
    ("Square310x310Logo.png",(310, 310),  "square"),
    ("Wide310x150Logo.png",  (310, 150),  "fit"),
    ("SplashScreen.png",     (620, 300),  "fit"),
]


# ── Version ───────────────────────────────────────────────────────

def read_version() -> str:
    """Read version.py and return a 4-part MSIX version string (x.y.z.0).

    The Store reserves the 4th (revision) component and requires it to be 0.
    """
    spec = importlib.util.spec_from_file_location("version", ROOT / "version.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    parts = str(mod.__version__).split(".")
    while len(parts) < 3:
        parts.append("0")
    major, minor, patch = (int(p) for p in parts[:3])
    return f"{major}.{minor}.{patch}.0"


# ── Identity ──────────────────────────────────────────────────────

def load_identity(test_mode: bool) -> dict:
    """Load identity.json. Auto-falls back to test values if the real Partner
    Center fields are still placeholders. Returns the resolved identity + a flag
    indicating whether the resulting package is sideload-only (test) or
    submission-ready (real)."""
    cfg = json.loads(IDENTITY_JSON.read_text(encoding="utf-8"))
    real_name = cfg.get("identity_name", "")
    real_pub = cfg.get("publisher", "")
    real_disp = cfg.get("publisher_display_name", "")

    placeholders_present = any(
        v.startswith(PLACEHOLDER_PREFIX) for v in (real_name, real_pub, real_disp)
    )

    if test_mode or placeholders_present:
        resolved = {
            "identity_name": cfg["test_identity_name"],
            "publisher": cfg["test_publisher"],
            "publisher_display_name": cfg["test_publisher_display_name"],
        }
        reason = "forced by --test" if test_mode else "Partner Center values not filled in yet"
        return {"values": resolved, "submission_ready": False, "reason": reason}

    return {
        "values": {
            "identity_name": real_name,
            "publisher": real_pub,
            "publisher_display_name": real_disp,
        },
        "submission_ready": True,
        "reason": "",
    }


# ── Logos ─────────────────────────────────────────────────────────

def generate_logos() -> None:
    """Generate every required Store logo size from assets/icon.png."""
    try:
        from PIL import Image
    except ImportError:
        sys.exit("[msix] ERROR: Pillow is required to generate logos. pip install pillow")

    if not SOURCE_ICON.exists():
        sys.exit(f"[msix] ERROR: source icon not found: {SOURCE_ICON}")

    ASSETS_OUT.mkdir(parents=True, exist_ok=True)
    src = Image.open(SOURCE_ICON).convert("RGBA")

    for name, (w, h), kind in LOGO_SPECS:
        if kind == "square":
            img = src.resize((w, h), Image.LANCZOS)
        else:  # "fit": scale icon to ~80% of the shorter side, center on transparent canvas
            target = int(min(w, h) * 0.8)
            scaled = src.resize((target, target), Image.LANCZOS)
            img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            img.paste(scaled, ((w - target) // 2, (h - target) // 2), scaled)
        img.save(ASSETS_OUT / name, "PNG")

    print(f"[msix] Generated {len(LOGO_SPECS)} logo assets -> {ASSETS_OUT}")


# ── Manifest ──────────────────────────────────────────────────────

def render_manifest(identity_values: dict, version: str) -> pathlib.Path:
    """Render AppxManifest.template.xml -> msix/build/AppxManifest.xml."""
    template = TEMPLATE.read_text(encoding="utf-8")
    rendered = (
        template
        .replace("__IDENTITY_NAME__", identity_values["identity_name"])
        .replace("__PUBLISHER__", identity_values["publisher"])
        .replace("__PUBLISHER_DISPLAY_NAME__", identity_values["publisher_display_name"])
        .replace("__VERSION__", version)
    )
    out = BUILD_DIR / "AppxManifest.xml"
    out.write_text(rendered, encoding="utf-8")
    print(f"[msix] Rendered manifest -> {out}")
    return out


# ── Mapping file (keeps dist/ untouched) ──────────────────────────

def build_mapping_file(dist_dir: pathlib.Path, manifest: pathlib.Path) -> pathlib.Path:
    """Write a makeappx [Files] mapping that references the existing dist/ tree
    in place (read-only) plus our generated manifest and Assets. Nothing is copied
    into dist/."""
    lines = ["[Files]"]

    # Every file in the PyInstaller output, mapped to the same relative path.
    file_count = 0
    for path in sorted(dist_dir.rglob("*")):
        if path.is_file():
            rel = path.relative_to(dist_dir).as_posix().replace("/", "\\")
            lines.append(f'"{path}" "{rel}"')
            file_count += 1

    # Manifest at the package root.
    lines.append(f'"{manifest}" "AppxManifest.xml"')

    # Generated logo assets.
    for name, _, _ in LOGO_SPECS:
        lines.append(f'"{ASSETS_OUT / name}" "Assets\\{name}"')

    mapping = BUILD_DIR / "mapping.txt"
    mapping.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[msix] Wrote mapping file ({file_count} app files) -> {mapping}")
    return mapping


# ── Windows SDK tools ─────────────────────────────────────────────

def find_sdk_tool(tool: str) -> str | None:
    """Locate a Windows SDK tool (makeappx.exe / signtool.exe), preferring the
    newest x64 version."""
    import shutil
    found = shutil.which(tool)
    if found:
        return found

    kits = pathlib.Path(r"C:\Program Files (x86)\Windows Kits\10\bin")
    if not kits.exists():
        return None
    candidates = sorted(kits.glob(f"*/x64/{tool}"), reverse=True)
    return str(candidates[0]) if candidates else None


def run_makeappx(mapping: pathlib.Path, version: str) -> pathlib.Path | None:
    makeappx = find_sdk_tool("makeappx.exe")
    if not makeappx:
        print(
            "\n[msix] makeappx.exe not found (Windows SDK not installed).\n"
            "       Install it, then re-run:\n"
            "         winget install Microsoft.WindowsSDK.10.0.26100\n"
            "       Everything else (manifest, logos, mapping) is ready in msix/build/."
        )
        return None

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_msix = OUTPUT_DIR / f"CanvasDownloader_{version}.msix"
    cmd = [makeappx, "pack", "/o", "/f", str(mapping), "/p", str(out_msix)]
    print(f"[msix] Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(ROOT))
    if result.returncode != 0:
        sys.exit(f"[msix] ERROR: makeappx exited with code {result.returncode}.")
    print(f"[msix] Package built -> {out_msix}")
    return out_msix


# ── Test signing (sideload only) ──────────────────────────────────

def test_sign(msix_path: pathlib.Path, publisher: str) -> None:
    """Generate a self-signed dev cert (subject == manifest Publisher) and sign
    the package so it can be sideloaded for local container testing."""
    signtool = find_sdk_tool("signtool.exe")
    if not signtool:
        print("[msix] signtool.exe not found - cannot test-sign. Install the Windows SDK.")
        return

    pfx = BUILD_DIR / "dev_cert.pfx"
    cer = BUILD_DIR / "dev_cert.cer"
    pw = "canvasdev"

    ps = (
        f"$c = New-SelfSignedCertificate -Type CodeSigningCert -Subject '{publisher}' "
        f"-CertStoreLocation Cert:\\CurrentUser\\My -KeyUsage DigitalSignature "
        f"-FriendlyName 'Canvas Downloader Dev' -TextExtension "
        f"@('2.5.29.37={{text}}1.3.6.1.5.5.7.3.3','2.5.29.19={{text}}'); "
        f"$pw = ConvertTo-SecureString -String '{pw}' -Force -AsPlainText; "
        f"Export-PfxCertificate -Cert $c -FilePath '{pfx}' -Password $pw | Out-Null; "
        f"Export-Certificate -Cert $c -FilePath '{cer}' | Out-Null; "
        f"Write-Output $c.Thumbprint"
    )
    print("[msix] Creating self-signed dev certificate...")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"[msix] Cert creation failed:\n{r.stderr}")
        return

    sign_cmd = [signtool, "sign", "/fd", "SHA256", "/a",
                "/f", str(pfx), "/p", pw, str(msix_path)]
    print(f"[msix] Signing: {' '.join(sign_cmd[:6])} ... {msix_path.name}")
    rs = subprocess.run(sign_cmd, cwd=str(ROOT))
    if rs.returncode != 0:
        print("[msix] Signing failed.")
        return

    print(
        "\n[msix] Test-signed OK. To install locally (run PowerShell as admin):\n"
        f'   Import-Certificate -FilePath "{cer}" -CertStoreLocation Cert:\\LocalMachine\\TrustedPeople\n'
        f'   Add-AppxPackage -Path "{msix_path}"\n'
        "   (This dev cert/package is sideload-only. Do NOT upload the signed copy\n"
        "    to the Store - submit the UNSIGNED package from a normal build instead.)"
    )


# ── Main ──────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Build the Microsoft Store MSIX package.")
    parser.add_argument("--test", action="store_true",
                        help="Self-sign with a dev cert for local sideload testing.")
    parser.add_argument("--dist", default=str(ROOT / "dist" / "Canvas Downloader"),
                        help="PyInstaller output folder to package (read-only).")
    parser.add_argument("--no-pack", action="store_true",
                        help="Generate manifest/logos/mapping only; skip makeappx.")
    args = parser.parse_args()

    dist_dir = pathlib.Path(args.dist).resolve()
    if not dist_dir.exists():
        sys.exit(
            f"[msix] ERROR: PyInstaller output not found: {dist_dir}\n"
            "       Build it first:  python build_windows.py --no-installer"
        )
    if not (dist_dir / "Canvas Downloader.exe").exists():
        sys.exit(f"[msix] ERROR: 'Canvas Downloader.exe' not found in {dist_dir}")

    version = read_version()
    identity = load_identity(test_mode=args.test)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[msix] Canvas Downloader MSIX  v{version}")
    print(f"[msix] Identity: {identity['values']['identity_name']} | "
          f"Publisher: {identity['values']['publisher']}")
    if not identity["submission_ready"]:
        print(f"[msix] NOTE: building a TEST (sideload-only) package - {identity['reason']}.")

    generate_logos()
    manifest = render_manifest(identity["values"], version)
    mapping = build_mapping_file(dist_dir, manifest)

    if args.no_pack:
        print("[msix] --no-pack set; stopping after mapping generation.")
        return

    msix_path = run_makeappx(mapping, version)
    if msix_path is None:
        return

    if args.test:
        test_sign(msix_path, identity["values"]["publisher"])
    elif identity["submission_ready"]:
        print(
            "\n[msix] Submission-ready UNSIGNED package built. Upload this file to\n"
            "       Partner Center (the Store signs it for you). Do not sign it yourself."
        )
    else:
        print(
            "\n[msix] Built an UNSIGNED test-identity package. It cannot be submitted\n"
            "       (identity is a placeholder) and cannot be installed unsigned.\n"
            "       Use --test to sideload-test, or fill in msix/identity.json from\n"
            "       Partner Center for a submission build."
        )

    print(f"\n[msix] Done. Version {version}.")


if __name__ == "__main__":
    main()
