"""
fake_quick_sync_setup.py  —  Opsæt fake Quick Sync til video-optagelse
Kør: python fake_quick_sync_setup.py          (apply)
     python fake_quick_sync_setup.py --undo   (gendannelse - se backup-mappen)

Vælger filer fra tre moduler der er synlige i screenshottet:
  NEW  (slet fra manifest + slet lokalt → Quick Sync downloader dem)
  UPDATE (behold filen lokalt, sæt gammel dato → Quick Sync overskriver rent)
"""

import argparse
import ctypes
import hashlib
import io
import os
import shutil
import sqlite3
import sys
from pathlib import Path

# Force UTF-8 output on Windows (avoids cp1252 UnicodeEncodeError for box chars)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


COURSE_ROOT = Path(r"C:\Users\birkl\Downloads\Introduction to Information Systems (LA E25 BINTO1078U)")
DB_PATH     = COURSE_ROOT / ".canvas_sync.db"
BACKUP_DIR  = COURSE_ROOT / "_fake_sync_backup"

OLD_DATE = "2020-01-01T00:00:00Z"   # gammel nok til at alle Canvas-filer er "nyere"

# ── Fil-valg ──────────────────────────────────────────────────────────────────
# Vises som "nye filer" Quick Sync finder og downloader
NEW_FILES = [
    # (canvas_file_id,  local_path_i_manifest)
    (1663166, "Module 6 - Managing, Acquiring, and Developing BIS/06_Managing, acquiring, and developing BIS.pdf"),
    (1700577, "Module 12 - Trends in IS/12_Quantum Computing.pdf"),
    (1632606, "Module 2 - BIS; Hardware & Software/Quality Board Ha(IT).pptx"),
]

# Vises som "opdaterede filer" Quick Sync downloader over den eksisterende
UPDATE_FILES = [
    # (canvas_file_id,  local_path_i_manifest)
    (1663167, "Module 6 - Managing, Acquiring, and Developing BIS/06_Enterprise & Functional BIS.pdf"),
    (1700576, "Module 12 - Trends in IS/12_Plattform Dominance.pdf"),
    (1628916, "Module 2 - BIS; Hardware & Software/02_Introduction to BIS, Hardware and Software.pdf"),
]
# ─────────────────────────────────────────────────────────────────────────────


def md5_of(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def unhide(p: Path):
    if os.name == "nt" and p.exists():
        ctypes.windll.kernel32.SetFileAttributesW(str(p), 0x80)


def rehide(p: Path):
    if os.name == "nt" and p.exists():
        ctypes.windll.kernel32.SetFileAttributesW(str(p), 0x02)


def apply():
    if not DB_PATH.exists():
        sys.exit(f"❌  DB ikke fundet: {DB_PATH}")

    BACKUP_DIR.mkdir(exist_ok=True)

    unhide(DB_PATH)
    con = sqlite3.connect(str(DB_PATH))

    print("\n── FAKE QUICK SYNC SETUP ────────────────────────────────────")

    # ── 1. NEW FILES: slet fra manifest + slet lokal fil ─────────────────────
    print("\n[NYE FILER] Sletter fra manifest + lokalt:")
    for fid, rel_path in NEW_FILES:
        local_file = COURSE_ROOT / rel_path

        # Backup lokal fil så vi kan gendanne
        if local_file.exists():
            bak = BACKUP_DIR / Path(rel_path).name
            shutil.copy2(local_file, bak)
            local_file.unlink()
            print(f"  ✓ Slettet fil   : {rel_path}")
            print(f"    Backup i       : {bak.name}")
        else:
            print(f"  ⚠  Fil ikke fundet lokalt (ok): {rel_path}")

        # Slet manifest-rækken
        deleted = con.execute(
            "DELETE FROM sync_manifest WHERE canvas_file_id = ?", (fid,)
        ).rowcount
        if deleted:
            print(f"    Slettet fra DB  : id={fid}")
        else:
            print(f"  ⚠  Ikke i DB (id={fid}) – allerede slettet?")

    # ── 2. UPDATE FILES: gammel dato + rigtig md5 → ren overskrivning ────────
    print("\n[OPDATERINGER] Sætter gammel canvas_updated_at:")
    for fid, rel_path in UPDATE_FILES:
        local_file = COURSE_ROOT / rel_path

        if not local_file.exists():
            print(f"  ⚠  Fil ikke fundet, springer over: {rel_path}")
            continue

        # Beregn md5 af den nuværende lokale fil så synkroniseringen
        # klassificerer den som 'clean' og overskriver i stedet for _NewVersion
        file_md5 = md5_of(local_file)

        rows = con.execute(
            "SELECT canvas_updated_at, original_size FROM sync_manifest WHERE canvas_file_id = ?",
            (fid,)
        ).fetchone()
        if not rows:
            print(f"  ⚠  Id={fid} ikke i DB, springer over")
            continue

        orig_date, orig_size = rows

        con.execute(
            """UPDATE sync_manifest
               SET canvas_updated_at = ?,
                   original_size     = 0,
                   original_md5      = ?
               WHERE canvas_file_id = ?""",
            (OLD_DATE, file_md5, fid),
        )
        print(f"  ✓ {Path(rel_path).name}")
        print(f"    Dato: {orig_date}  →  {OLD_DATE}")
        print(f"    Størrelse: {orig_size}  →  0  (så Canvas-størrelsen er 'ændret')")
        print(f"    MD5 gemt (ren overskrivning, ikke _NewVersion): {file_md5[:12]}…")

    con.commit()
    con.close()
    rehide(DB_PATH)

    print("\n────────────────────────────────────────────────────────────")
    print("✅  Klar til optagelse!")
    print(f"   3 nye filer  → Quick Sync finder og downloader dem")
    print(f"   3 opdateringer → Quick Sync overski-ver dem rent")
    print(f"\n   Gendannelse: python {Path(__file__).name} --undo")


def undo():
    """Gendannelse: kopier backup-filer tilbage (manifest gendannes ikke - kør bare et sync)."""
    if not BACKUP_DIR.exists():
        sys.exit("❌  Ingen backup-mappe fundet. Kan ikke gendanne.")

    print("\n── GENDANNELSE ──────────────────────────────────────────────")
    for fid, rel_path in NEW_FILES:
        bak = BACKUP_DIR / Path(rel_path).name
        dest = COURSE_ROOT / rel_path
        if bak.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(bak, dest)
            print(f"  ✓ Gendannet: {rel_path}")
        else:
            print(f"  ⚠  Backup ikke fundet: {bak.name}")

    print("\n  NB: Manifest-ændringer gendannes ikke automatisk.")
    print("      Kør Quick Sync igen for at genopbygge manifestet korrekt.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--undo", action="store_true", help="Gendannelse")
    args = parser.parse_args()

    if args.undo:
        undo()
    else:
        apply()
