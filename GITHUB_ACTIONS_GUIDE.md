# GitHub Actions Build Guide — Canvas Downloader macOS

> **Audience**: You have never used GitHub Actions before and want to build the
> macOS `.app` in the cloud without needing a Mac.
>
> **What this does**: GitHub runs a real macOS machine on their servers,
> installs all dependencies, compiles the app with PyInstaller, signs it,
> and hands you a downloadable `.zip` — all for free on a public repository.

---

## What You Need Before Starting

- The Canvas Downloader code pushed to a **GitHub repository** (public or private).
- The `.github/workflows/build-macos.yml` file already exists in the repo (it was
  created alongside this guide).
- That's it. No Mac, no Apple account, no certificates required.

---

## Step 1 — Make Sure the Workflow File Is in the Repo

The workflow file lives at:
```
.github/workflows/build-macos.yml
```

If you just cloned or pulled the repo and this file is present, you are ready.
Commit and push it if you haven't already:

```bash
git add .github/workflows/build-macos.yml
git commit -m "Add macOS GitHub Actions build workflow"
git push
```

---

## Step 2 — Trigger the Build

1. Open your repository on **github.com**.
2. Click the **Actions** tab (top of the page, between "Pull requests" and "Projects").
3. In the left sidebar you will see **"Build macOS"** listed under "All workflows".
4. Click **"Build macOS"**.
5. Click the **"Run workflow"** button on the right side of the page.
6. A small dropdown appears. Leave everything as-is and click the green
   **"Run workflow"** button inside the dropdown.

The build starts. You will see one job appear:
- **Build macOS (.app)** — runs on a GitHub-hosted Apple Silicon Mac (`macos-latest`).

---

## Step 3 — Wait for the Build to Finish

The job takes **just a few minutes** because it leverages a lightweight Bring Your Own Browser (BYOB) architecture.

You can watch live logs by clicking on either job name. A green checkmark means
success. A red X means something failed — see [Troubleshooting](#troubleshooting)
below.

---

## Step 4 — Download the Built `.app`

Once the job shows a green checkmark:

1. Click the **"Build macOS"** run (the row with the run name/number).
2. Scroll to the bottom of the run page to the **Artifacts** section.
3. You will see one artifact: `Canvas_Downloader_macOS`
4. Click it to download a `.zip` file containing the `.dmg`.

> **Artifact expiry**: Artifacts are kept for **30 days** and then deleted
> automatically by GitHub. Download them before then.

---

## Step 5 — What's Inside the Downloaded `.zip`

The downloaded `.zip` contains:
```
Canvas_Downloader_macOS.dmg     ← standard macOS disk image
```

To distribute the app, share the `.dmg` directly. Users mount the `.dmg` and copy `Canvas Downloader.app` to their `/Applications` folder.

---

## Step 6 — First-Launch Warning (Gatekeeper)

Because the app is **ad-hoc signed** (not signed with a paid Apple Developer
certificate), macOS will show a warning the first time a user opens it:

> *"Canvas Downloader" cannot be opened because the developer cannot be verified.*

**Fix for users:** Right-click (or Control-click) the app → **Open** → click **Open**
in the dialog. macOS remembers this choice and will not ask again.

This is a one-time step per machine. It is documented in `README_INSTALL.md`.

---

## Artifacts vs. GitHub Releases

| | Artifacts (what this workflow does) | GitHub Releases |
|---|---|---|
| Where | Actions → run → Artifacts section | Releases tab |
| Expires | After 30 days | Never |
| Download link | Not a permanent URL | Permanent URL |
| Setup effort | Zero (automatic) | Requires extra workflow steps |

For now, artifacts are fine for testing and internal sharing. If you want a
permanent public download page (like `v2.0.0` on the Releases tab), that
requires adding a release step to the workflow — ask when you're ready for that.

---

## How to Re-Run the Build

Every time you push changes and want a new build:
1. Go to Actions → Build macOS → Run workflow.
2. That's it. Each run is independent and produces fresh artifacts.

You do not need to change any code in the workflow file itself unless the
build process changes (e.g., a new dependency is added to `requirements.txt`).

---

## Troubleshooting

### Build fails with `ModuleNotFoundError`
A Python package failed to install. Click the failed job → expand the
**"Install dependencies"** step to see which package caused the error.
Usually fixable by checking that `requirements.txt` is correct and committed.

### Build fails with `FileNotFoundError: assets/icon.icns`
The `assets/` folder was not committed to the repo. Make sure
`assets/icon.icns` is tracked by git (not in `.gitignore`).

### Build fails with `No such file or directory: 'entitlements.plist'`
The `entitlements.plist` file is missing from the repo root. Commit it.

### Job is stuck at "Set up Python"
GitHub's servers are occasionally slow. Wait a few minutes and re-run.

### `codesign` step fails
This is rare on GitHub-hosted runners since `codesign` is always available
as part of Xcode. If it happens, check that the PyInstaller step before it
actually produced `dist/Canvas Downloader.app`.



---

## Workflow File Reference

The workflow is at [.github/workflows/build-macos.yml](.github/workflows/build-macos.yml).
Key settings at a glance:

| Setting | Value | Meaning |
|---|---|---|
| Trigger | `workflow_dispatch` | Manual only — never runs automatically |
| Python | `3.13` | Matches your local development version |
| Runner | `macos-latest` | GitHub-hosted Apple Silicon Mac |
| Signing | Ad-hoc (`-s -`) | Free, no Apple account needed |
| Artifact retention | 30 days | Auto-deleted after 30 days |
