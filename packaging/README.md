# Packaging: getting the app into package managers

Written 2026-08-28. The reasoning for *why* these channels matter is in
`marketing/DISTRIBUTION.md` section 2, which is LOCAL-ONLY: `marketing/` is gitignored
as of 2026-08-28, so that is deliberately not a link and is not in a clone. This file
is the mechanics: what is here, how to submit it, and what will go wrong.

Everything here was generated against the **published v2.0.2 release assets**
and the hashes were computed from the downloaded files, not from a local build.

---

## STATUS as of 2026-08-28

| Item | State |
|---|---|
| winget-pkgs PR | **OPEN**, CLA signed, 8 checks green, 0 failures - <https://github.com/microsoft/winget-pkgs/pull/425661> |
| `WINGET_TOKEN` secret | **SET** 2026-08-28 13:22 UTC |
| `birkls/winget-pkgs` fork | **EXISTS** - the workflow pushes its branch here every release. Do not delete it |
| `.github/workflows/winget.yml` | **COMMITTED AND PUSHED** 2026-08-28 in `b6c81f0d`; `main` is level with `origin/main` |
| Homebrew | **DROPPED** - built, published, deleted the same day. See section 2 |

**The automation is live.** The workflow was committed and pushed the same day,
so the secret now has something to run. It is still unproven: nothing has cut a
release since, so the first real test is the next tag, and the failure mode to
watch for is a listing that silently keeps describing 2.0.2.

**PR state re-read from the API 2026-08-28 evening:** `open`, `merged: false`,
labels `Azure-Pipeline-Passed`, `Validation-Completed`, `New-Package`. The only
comment after the CLA is the bot's *"check-in policies require a moderator to
approve PRs from the community"*. **There is nothing to do and nothing to bump**
- a comment on a queued winget PR is noise to a volunteer moderator, not a
nudge.

**What the PR is waiting on** is a maintainer's approving review, not anything on
this side. `08. Installation Validation` runs the installer in a sandbox VM,
which is the check `winget install --manifest` would have anticipated locally -
it was skipped deliberately (see section 6) and the PR says so rather than
claiming otherwise.

**A stale `GITHUB_TOKEN` was removed from the User environment on 2026-08-28.**
It was a 40-character classic PAT returning HTTP 401. `gh` prefers that variable
over its own keyring, so every `gh` call failed while a working keyring login sat
behind it, and `gh auth status` reported the good account as
`Active account: false`. **`git` was never affected** - it uses
`credential.helper=manager`, a different credential path entirely - which is why
the breakage was invisible for however long it had been there. The 401 rules out
the account's live token, so the value was an expired one.

**Lesson worth keeping:** when a GitHub tool misbehaves, check `GITHUB_TOKEN`
before anything else, and remember that git working normally proves nothing
about `gh`.

| Asset | Bytes | SHA256 |
|---|---|---|
| `Canvas_Downloader_v2.0.2_Windows.exe` | 91,851,637 | `4a3acedcb9fa636cf1438a9d10d66c8a735709437efaa609e8005679cd43d5a5` |

---

## 1. winget - ready to submit

### What is here

`winget/` holds the three manifests winget requires, already filled in:

```
BrkBuilds.CanvasDownloader.yaml               version manifest
BrkBuilds.CanvasDownloader.installer.yaml     installer + hash + product code
BrkBuilds.CanvasDownloader.locale.en-US.yaml  the listing copy
```

Facts they encode, each read out of the build rather than assumed:

| Field | Value | Source |
|---|---|---|
| `InstallerType` | `inno` | `Canvas_Downloader_Setup.iss` |
| `Scope` | `user` | `PrivilegesRequired=lowest` |
| `Architecture` | `x64` | `ArchitecturesInstallIn64BitMode=x64compatible` |
| `ProductCode` | `{A3F2D1E0-...-5D6B3A1F8E2D}_is1` | `AppId` in the `.iss`, plus Inno's `_is1` suffix |
| `License` | `GPL-3.0-or-later` | the 2026-08-24 relicense |

**The `{{` in the `.iss` `AppId` is Inno's escape for a literal `{`.** The real
GUID is single-braced, and the uninstall key Inno writes appends `_is1`. Get
this wrong and winget cannot detect an existing install or perform an upgrade.

### How to submit

```
winget install wingetcreate
wingetcreate submit --token <github-pat> packaging/winget/
```

`wingetcreate` forks `microsoft/winget-pkgs`, places the files under
`manifests/b/BrkBuilds/CanvasDownloader/2.0.2/` and opens the PR. Doing it by
hand works too; the path is the part people get wrong.

**Validate before submitting.** `winget validate --manifest packaging/winget/`
catches schema errors locally, and the PR pipeline runs a real install in a
sandbox VM. A failed sandbox install is the usual rejection.

### What to expect

The automated pipeline installs, checks the `ProductCode` resolves, and
uninstalls. **SmartScreen is not part of that check** - winget verifies the
SHA256 itself, which is exactly why this channel is worth having.

### Keeping it current - this is the part that rots

A new release needs a new PR. Automate it or it will go stale the way the Store
listing did (`marketing/FINDINGS.md` records that one sitting on v2.0.0 with a
404 privacy link for ten weeks):

```yaml
- name: Publish to winget
  uses: vedantmgoyal9/winget-releaser@main
  with:
    identifier: BrkBuilds.CanvasDownloader
    installers-regex: '_Windows\.exe$'
    token: ${{ secrets.WINGET_TOKEN }}
```

Add that to the release workflow. It needs a classic PAT with `public_repo`
scope and a fork of `winget-pkgs` on the account.

---

## 2. Homebrew - BUILT, THEN DROPPED. Do not rebuild it

**Decided by the product owner 2026-08-28, after it had been built and briefly
published.** Recorded in full because the instinct to add a Homebrew cask is
strong, `PLAYBOOK.md` section 6 still calls casks "the practical macOS channel",
and without this note the next session will simply do it again.

### What was built and then removed

A complete, valid cask, plus a public tap at `BrkBuilds/homebrew-tap` holding it
alongside a README. Both are gone: the local files were deleted before ever
being committed, and the tap repository was deleted by the operator.

### Why it was dropped - the audience is 2.8% of installs

Measured from the GitHub API, 2026-08-28:

| Channel | Downloads |
|---|---|
| GitHub, Windows, all releases ever | 35 |
| **GitHub, macOS, all releases ever** | **28** |
| Microsoft Store (Windows only) | 939 |

macOS is **28 of 1,002 known installs**. Because the Store is Windows-only,
those 28 are not a sample - they are the entire lifetime macOS population.

**And a tap has no discovery.** `brew search` cannot see a tap the user has not
already added, so it reaches nobody who does not already know the project
exists. It would serve the subset of 28 people who use Homebrew *and* read the
README - realistically a handful, all of whom had already managed to download a
DMG unaided.

### The other blocker, which stands regardless

Even the official `homebrew-cask` route was closed. From Homebrew's
[Acceptable Casks](https://docs.brew.sh/Acceptable-Casks), checked 2026-08-28:

> "apps, installers and other executable artefacts that Gatekeeper can assess
> must pass Homebrew's Gatekeeper checks and must not require System Integrity
> Protection or Gatekeeper to be disabled or bypassed."

This app is ad-hoc signed and not notarized - `CLAUDE.md` records
`spctl -a -t exec` returning *rejected*, **exit 3** - and `mac-setup.html`
instructs the user to click **Open Anyway**, which is the bypass that rule
names. Notarization needs a paid Apple Developer account, which `CLAUDE.md`
settles as out of scope and says not to re-raise.

**Notability was NOT the blocker**, contrary to the first assumption in this
file. That document carries no numeric star or fork threshold and explicitly
says *"The shared notability metrics may not represent the notability of an
established application when the repository is used only to host its
binaries."* Worth knowing so the 2-star count is not misdiagnosed as the reason.

### If it is ever revisited

Two conditions would have to change together: the macOS share would have to grow
enough to be worth the maintenance, and the app would have to be notarized. Post
a measurement, not an argument.

### One detail worth keeping

The cask needed `depends_on arch: :arm64`. `build-macos.yml` runs on `macos-14`,
an Apple Silicon runner, and the spec has no `universal2` target, so the shipped
DMG is arm64-only. Any future macOS packaging - Homebrew or otherwise - has to
declare that, or an Intel Mac installs successfully and then gets an app that
cannot launch.

---

## 3. Prerequisites on the release machine

### A stale GITHUB_TOKEN is shadowing the working login - fix this first

Measured on the operator's machine 2026-08-28:

```
gh api user   (with GITHUB_TOKEN set)    -> "Bad credentials"
gh api user   (with GITHUB_TOKEN empty)  -> birkls
```

A 40-character classic PAT is set as a **User** environment variable and is no
longer valid. `gh` prefers `GITHUB_TOKEN` over its own keyring, so every `gh`
command fails while a perfectly good keyring login sits behind it - and
`wingetcreate submit` reads the same variable.

Delete it (the keyring login takes over immediately):

```powershell
[Environment]::SetEnvironmentVariable('GITHUB_TOKEN', $null, 'User')
```

Then open a new terminal. **Also revoke that PAT** at
<https://github.com/settings/tokens> - it is dead for auth but it should not be
left lying in the environment.

### wingetcreate is not installed

```
winget install Microsoft.WingetCreate
```

---

## 4. Automation: the winget manifest updates itself

[`.github/workflows/winget.yml`](../.github/workflows/winget.yml) submits a new
manifest on every published release, using `vedantmgoyal9/winget-releaser@v2`
(verified active 2026-08-28, last pushed 2026-07-28).

It triggers on `release: published` rather than sitting in a build job, because
the Windows installer is built on the operator's own machine and only the macOS
DMG is built in CI. `workflow_dispatch` is kept so a rejected PR can be re-run
against an existing tag.

**Two things it needs before the first run:**

1. A fork of `microsoft/winget-pkgs` on the account.
2. A repository secret **`WINGET_TOKEN`** - a classic PAT with `public_repo`
   scope. The default `GITHUB_TOKEN` cannot push a branch to a fork of another
   repo, so this cannot be skipped.

---

## 5. Chocolatey and Scoop

Not built. See `marketing/DISTRIBUTION.md` section 2c: worth doing after winget
lands, or not at all.

---

## 6. What was verified, and what was not

**Verified:**
- The Windows `InstallerSha256`, computed from the downloaded published asset;
  its size matches what the GitHub API reports, and the URL returns HTTP 200.
- `winget validate --manifest packaging\winget` reports
  **"Manifest validation succeeded"** - Microsoft's own schema check.
- All three manifests parse, carry every required field, agree on identifier and
  version, and sit inside the tag and description budgets.
- Every installer fact traced to `Canvas_Downloader_Setup.iss`.
- The Homebrew rules quoted in section 2, fetched from `docs.brew.sh`.
- The install counts behind the Homebrew decision, from the GitHub API.

**NOT verified:**
- **`winget install --manifest` has never been run.** The PR's checklist box for
  it is deliberately left UNCHECKED with a note saying so. It was skipped
  because it would install v2.0.2 over whatever build is on the machine, which
  is the operator's call. If a reviewer asks, run it and report back.
- The manifests have not been through the winget-pkgs pipeline; it is blocked
  behind the unsigned CLA.
- `MinimumOSVersion: 10.0.17763.0` in the installer manifest is a **reasonable
  assumption, not a measurement** - it is the usual floor for a modern
  PyInstaller and WebView2 app. If the app has a documented Windows floor,
  correct it; nothing in the build declares one.
