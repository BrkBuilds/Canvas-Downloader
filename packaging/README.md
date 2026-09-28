# Packaging: package managers, and why the app is in none of them

Written 2026-08-28, rewritten 2026-09-26. The reasoning for *why* these channels matter is in
`marketing/DISTRIBUTION.md` section 2, which is LOCAL-ONLY: `marketing/` is gitignored
as of 2026-08-28, so that is deliberately not a link and is not in a clone. This file
is the mechanics: what is here, how to submit it, and what will go wrong.

Everything here was generated against the **published v2.0.2 release assets**
and the hashes were computed from the downloaded files, not from a local build.

---

## STATUS as of 2026-09-26

| Item | State |
|---|---|
| winget | **DROPPED 2026-09-26** by the product owner, after a moderator blocked the PR on policy. See section 1 |
| Homebrew | **DROPPED 2026-08-28** - built, published, deleted the same day. See section 2 |
| Chocolatey, Scoop | Not built. Section 5 |

The Microsoft Store, GitHub Releases and the website are the channels. The Store
alone is ~94% of installs.

**A lesson from the winget work that outlives it:** a stale `GITHUB_TOKEN` in the
User environment (a dead classic PAT, HTTP 401) made every `gh` call fail while a
working keyring login sat behind it, because `gh` prefers the variable. `git` was
unaffected - it uses `credential.helper=manager` - which is why it went unnoticed.
When a GitHub tool misbehaves, check `GITHUB_TOKEN` first; git working proves
nothing about `gh`. The variable was removed 2026-08-28.

---

## 1. winget - SUBMITTED, BLOCKED ON POLICY, THEN DROPPED

The community-repo PR (<https://github.com/microsoft/winget-pkgs/pull/425661>,
"New package: BrkBuilds.CanvasDownloader version 2.0.2") passed every automated
check and was then stopped by a moderator, 2026-09-26, under template
`msftbot/validationError/policy/contentPermissions`:

> The application's disclaimer states that it downloads a recording's video
> stream even when the institution or instructor has disabled Panopto's download
> button. This bypasses a content-owner-controlled restriction and may enable
> copying contrary to institutional rules, Panopto's terms, or the rights
> holder's intent. A disclaimer assigning responsibility to the user does not
> resolve that behavior.
>
> Please update the application so Panopto downloads respect the recording's
> download-permission setting.

**Dropped rather than fixed.** Its reach is small (the app was already in winget
through the automatic `msstore` source), and complying means changing the
Panopto feature itself, which is a product decision and not a packaging one.

Removed on the same day, so nothing re-submits it behind anyone's back:
`.github/workflows/winget.yml` (it opened a new PR on EVERY published release)
and the three manifests in `packaging/winget/`. Both are in git history if the
decision is ever reversed. Outside the repo, 2026-09-26: the PR was CLOSED with
a one-line withdrawal comment, and the `WINGET_TOKEN` repository secret was
DELETED, and the `birkls/winget-pkgs` fork was DELETED (it needed the
`delete_repo` scope, granted with `gh auth refresh -h github.com -s delete_repo`).

**THE SAME OBJECTION IS WHERE THE REAL RISK IS.** The moderator quoted the app's
own disclaimer - `DISCLAIMER.md`, `docs/disclaimer.html`, the README and the
in-app acceptable-use notice (`shared/legal.py`) all say it. The
Microsoft Store runs its own certification against Microsoft policy, and nothing
here establishes whether it would reach the same conclusion. Recorded so that a
Store rejection citing content permissions is recognised as this, not
re-diagnosed from scratch. See `.claude/rules/panopto.md` for the posture itself.

**If winget is ever reconsidered:** it needs Panopto to honour the
download-permission flag first. Everything else was done and passed - the PR
cleared `Azure-Pipeline-Passed` and `Validation-Completed`, and
`winget validate` reported the manifests valid. The `ProductCode` is the `.iss`
`AppId` single-braced plus Inno's `_is1` suffix (the `{{` in the `.iss` is Inno's
escape), and `Scope` is `user` from `PrivilegesRequired=lowest`.

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

## 3. Chocolatey and Scoop

Not built. Both are community repositories with human moderators, so the
content-permission objection in section 1 is likely to come back there too.

---
