# Canvas Downloader - Microsoft Store (MSIX) track

This folder is the **separate** Microsoft Store packaging track. It is a
*supplement* to the main Inno Setup `.exe` installer that ships on GitHub - it
does **not** modify `build_windows.py`, `Canvas_Downloader_Setup.iss`, or the
`dist/` contents. The `.msix` is built from the existing PyInstaller output,
referenced read-only via a `makeappx` mapping file.

Why MSIX for the Store: **free code signing** (the Store signs the package, so no
paid certificate), **automatic updates**, and **no SmartScreen warning** - which
is the whole point for students installing it.

```
msix/
  AppxManifest.template.xml   # manifest with __PLACEHOLDER__ tokens (committed)
  identity.json               # Partner Center identity values (committed; fill in)
  README.md                   # this file
  build/                      # generated: manifest, logos, mapping, dev cert (gitignored)
build_msix.py                 # the build script (committed)
msix_output/                  # generated: CanvasDownloader_<ver>.msix (gitignored)
```

---

## One-time setup

### 1. Install the Windows SDK (provides `makeappx.exe` + `signtool.exe`)
```powershell
winget install Microsoft.WindowsSDK.10.0.26100
```

### 2. Reserve the app name in Partner Center
1. Partner Center → **Apps and games** → **New product** → **MSIX or PWA app**.
2. Reserve the name (e.g. `Canvas Downloader`).
3. Open the product → **Product management → Product identity**. Copy these three
   values into `msix/identity.json`:

   | identity.json field        | Partner Center label                          |
   |----------------------------|-----------------------------------------------|
   | `identity_name`            | **Package/Identity/Name**                     |
   | `publisher`                | **Package/Identity/Publisher** (`CN=…`)       |
   | `publisher_display_name`   | **Package/Properties/PublisherDisplayName**   |

Until those are filled in, `build_msix.py` builds a **test** package (sideload
only) using the `test_*` values in `identity.json`.

---

## Build

Build the app first (this is your normal build - unchanged):
```powershell
python build_windows.py --no-installer     # produces dist/Canvas Downloader/
```
Then build the Store package:
```powershell
python build_msix.py
# -> msix_output/CanvasDownloader_<ver>.msix   (UNSIGNED - the Store signs it)
```

### Test it locally before submitting (recommended)
Verifies the app actually runs inside the MSIX container (WebView2, Office→PDF COM,
keyring, %APPDATA% writes) before you upload:
```powershell
python build_msix.py --test
# then, in an ADMIN PowerShell, run the two commands it prints:
#   Import-Certificate -FilePath ".\msix\build\dev_cert.cer" -CertStoreLocation Cert:\LocalMachine\TrustedPeople
#   Add-AppxPackage -Path ".\msix_output\CanvasDownloader_<ver>.msix"
```
The `--test` package is sideload-only. **Never upload a self-signed package** -
submit the UNSIGNED package from a plain `python build_msix.py`.

---

## Submit to the Store
1. In the reserved product → **Packages** → upload `msix_output/CanvasDownloader_<ver>.msix`.
2. Fill in **Store listing** (description, features, screenshots - `assets/screenshot_*.png`
   work), the mandatory **Store logo**, **Age ratings**, **Pricing** (Free).
3. Submit for certification.

### Updating later
Bump `version.py`, rebuild (`build_windows.py` then `build_msix.py`), upload the new
`.msix`. The MSIX `Version` is always `x.y.z.0` (the Store reserves the 4th part).
Keep the same reserved identity so the Store treats it as an update.

> The Inno Setup `.exe` on GitHub and this MSIX are independent distributions of
> the same app. A user could have either; they are not linked and do not share an
> install location.
