# Repository setup and discoverability

Everything in this file has to be set in the GitHub web UI, because it lives in GitHub's database
rather than in the tree. No amount of grepping the repository will ever find it, which is exactly
why it is written down here.

Target after the move: **`github.com/BrkBuilds/Canvas-Downloader`**

---

# STATUS - 2026-08-19

Read this section first. It is the handoff between machines: assistant memory does
not travel between the laptop, the desktop and the mac box, so anything that has to
survive a machine change lives in the repository. Pull before starting.

## Done

- **Organisation created**: `BrkBuilds`, contact `brkbuilds1@gmail.com`, ko-fi linked,
  avatar set.
- **Repository renamed and transferred**: `birkls/Canvas_LMS_batch_file_downloader`
  is now `BrkBuilds/Canvas-Downloader`. Old URLs 301 permanently.
- **DNS updated**: `www` CNAME now points at `brkbuilds.github.io`, DNS only.
  Verified live: apex returns 200, `www` 301s to apex.
- **URL migration applied**: 85 references across 22 files, including the three that
  compile into the binaries (`ui/auth.py` x2, `ui/update_banner.py`). The dated record
  `tests/audit/WEBSITE_LAUNCH_AUDIT.html` was deliberately left holding the old URLs.
- **About panel**: description and all 20 topics set, website field points at
  canvasdownloader.app.
- **`brkbuilds1@gmail.com` verified** on the birkls account. This clone's git identity
  is `BrkBuilds <brkbuilds1@gmail.com>` (repo-local, so other projects are unaffected).
  **A fresh clone on another machine does NOT inherit this** - see "On a new machine".
- **README rewritten**: version drift fixed (dynamic badge), 81 modules / 4.3 MB,
  3,827 tests, plus the Panopto Shortcut output, the institution picker and the global
  Panopto switch, none of which were documented before. Added a FAQ and a comparison
  table for long-tail search.
- **Community files**: CONTRIBUTING, SECURITY, CODE_OF_CONDUCT, issue forms, PR
  template, FUNDING.
- Committed and pushed as `e4f949e`. Suite green (3,810 passed, 17 skipped),
  architecture audit 0 violations.

## To do

1. **Six README screenshots.** Capture spec in `docs/assets/screenshots/README.md`.
   Save with the exact filenames, then run
   `python scripts/optimize_screenshots.py --apply` and uncomment the screenshot block
   in README.md. Decide first whether real CBS course names should be public.
2. **Social preview image.** **Now unblocked**: `docs/assets/github-social-preview.png`
   exists and is exactly **1280x640** (verified 2026-08-20). The GitHub API still reports
   no custom Open Graph image, so it has not been uploaded yet.
   Settings, General, Social preview.
3. ~~Description typo.~~ **DONE 2026-08-19** - verified live, 252 chars, no double space.

4. **Turn on Discussions** (Settings, General, Features). Absorbs the recurring
   "how do I get my token" and "does it work with my university" questions, and
   threads get indexed.
5. **Rebuild the Windows and macOS bundles.** Not urgent - the redirect covers the
   three compiled URLs - but new builds should point straight at the new address.
   Note `version.py` is at 2.0.2 while the latest tag is v2.0.1.
6. **Fix the release notes.** v2.0.1 carries five stale links, four of which are hard
   404s (see "What DOES break" below). v2.0.0 and v1.0.0 carry redirecting ones. Exact
   replacement text is in `marketing/PLAYBOOK.md` section 1b.
7. Optional: pin the repository on the org profile, and give `BrkBuilds` a profile
   README via a `.github` repository.

**Marketing, SEO and launch memory lives in `marketing/`** - findings register, settled
decisions, the site runbook and the off-site playbook. That folder is gitignored as of
2026-08-28 and is LOCAL-ONLY, so this is deliberately not a link: it is not in a clone,
it does not travel between machines, and nothing tracked may depend on a file inside it.

## On a new machine

A fresh clone uses your GLOBAL git identity, which is still
`birkls <birk.lykkeberg@gmail.com>`. To author as the developer identity there:

```bash
git config user.name  "BrkBuilds"
git config user.email "brkbuilds1@gmail.com"
```

Both addresses are verified on the account, so either links correctly. This is only
about which name appears on the commit.

---

---

## 1. The move: org transfer and rename

Do these **one at a time**, checking the site in between, so that if something breaks you know which
step did it.

### Step 1 - Rename the repository

Still under `birkls`: **Settings → General → Repository name** → `Canvas-Downloader` → **Rename**.

Then load <https://canvasdownloader.app> and confirm it still works.

### Step 2 - Transfer to the organisation

**Settings → General → Danger Zone → Transfer ownership** → new owner `BrkBuilds`.

Stars, forks, issues, pull requests and watchers all move with it.

### Step 3 - Fix DNS (this one is required, and it is the only external step)

In Cloudflare, the `www` record must follow the account name:

| Record | Was | Becomes |
|---|---|---|
| `www` CNAME | `birkls.github.io` | `brkbuilds.github.io` |
| apex `A` x4 | `185.199.108-111.153` | **unchanged**, these are GitHub's own IPs |
| apex `AAAA` x4 | `2606:50c0:800{0..3}::153` | **unchanged** |

Every record stays **DNS only (grey cloud)**. Cloudflare shows a standing amber banner pushing you to
enable the proxy. Ignore it - a proxied record breaks GitHub's certificate issuance.

### Step 4 - Re-check Pages

**Settings → Pages.** A transfer sometimes clears the custom domain field. If it is blank, retype
`canvasdownloader.app` and save. `docs/CNAME` is unchanged in the tree, so the certificate
re-provisions on its own.

`.app` is HSTS-preloaded, so while the certificate provisions you get a **security error, not a
404**. Chrome caches that hard - check in an incognito window before concluding it failed.

### Step 5 - Update the local remote

```bash
git remote set-url origin https://github.com/BrkBuilds/Canvas-Downloader.git
git remote -v
```

### Step 6 - Rewrite the hardcoded URLs in the tree

```bash
python scripts/migrate_repo_urls.py            # dry run first
python scripts/migrate_repo_urls.py --apply
python -m pytest                               # confirm still green
```

Run this **after** the move, never before. GitHub 301s the old URL to the new one, so a tree still
holding old URLs is merely stale and every link keeps working. A tree holding new URLs before the
move is broken.

### What does NOT break

- **Old links keep working, permanently.** Verified against a real owner change: `facebook/jest`
  returns 301 then 200 on both `github.com` and `api.github.com`. Only you could ever break that
  redirect, by creating a new repo under the old name.

### What DOES break, and step 6 cannot reach it

Added 2026-08-20 after finding both of these live.

- **The old GitHub PAGES host does NOT redirect.** The bullet above is true of
  `github.com` and false of `<old-owner>.github.io`. A project Pages site simply stops existing
  once the site moves to a custom domain. Measured:
  `https://birkls.github.io/Canvas_LMS_batch_file_downloader/` returns a hard **404**.
- **Release notes live on GitHub, not in the tree**, so `scripts/migrate_repo_urls.py` cannot
  touch them. The v2.0.1 notes carried **five** stale links, four of them the `github.io` kind
  above, including the headline "Website & guides" link at the top. That is the page anyone
  clicking "Releases" lands on, and Google indexes it. **Edit every release's notes by hand
  after a move.**
- **The script matches two exact strings**, so a third spelling survives silently.
  `Canvas_Downloader_Setup.iss` held `github.com/birkls/canvas-downloader` (old owner, lowercase
  hyphenated repo), which is neither `<old-owner>/<old-repo>` nor a bare `<old-repo>`. It is the
  publisher URL Windows shows in Apps & features.
  `tests/test_no_stale_repo_urls.py` now scans for stale *links* of any spelling, and passes.
- **Do not lean on the redirect indefinitely.** A released GitHub username can be claimed by
  somebody else, at which point a URL baked into a shipped installer resolves to their account.
- **Shipped v2.0.0 and v2.0.1 binaries keep checking for updates.** `ui/update_banner.py` calls the
  API through `requests.get`, which follows redirects by default. Users on old builds are fine.
- **Search Console for `canvasdownloader.app` is unaffected.** It is a domain property verified by
  DNS TXT, which has nothing to do with who owns the GitHub repo.

### Rebuild the binaries when convenient

Three URLs are compiled into the app: two "View source on GitHub" links in `ui/auth.py` and the
releases API endpoint in `ui/update_banner.py`. They work through the redirect, so this is not
urgent, but the next Windows and macOS builds should be made after step 6 so new downloads point
straight at the new address.

---

## 2. About panel

**Settings → General**, or the gear icon beside "About" on the repository home page.

### Description

This is the single highest-value SEO field on the whole repository. Google renders the repo page
title as `GitHub - BrkBuilds/Canvas-Downloader: <description>`, so these words are literally the
page title in search results.

```
Download all your Canvas LMS files at once. Free Windows and macOS app with automatic course sync, Panopto lecture downloads, offline transcription and NotebookLM-ready conversion.
```

It front-loads the exact phrase people search for, names both platforms, and covers the four
distinct things the app does. 178 characters, so it is not truncated in the About panel.

### Website

```
https://canvasdownloader.app
```

Set this. It is a real link between the two properties, and the repository is currently the stronger
of the two.

### Topics

Paste these 20. Topics are a GitHub search facet and each one has its own indexed page.

```
canvas-lms
canvas
canvas-downloader
downloader
file-downloader
batch-download
bulk-download
lms
education
edtech
student-tools
panopto
lecture-recordings
transcription
whisper
notebooklm
desktop-app
python
streamlit
offline
```

Twenty is the maximum. The mix is deliberate: brand terms so a branded search finds it, intent terms
(`batch-download`, `bulk-download`) because that is what the query looks like, feature terms so
Panopto and NotebookLM users find it from a different direction, and only three tech terms, because
`python` alone is millions of repos and does nothing for discovery on its own.

### Checkboxes

- Releases: **on**
- Packages: off
- Deployments: off

---

## 3. Social preview image

**Settings → General → Social preview → Upload an image.**

This is what renders when the repository link is posted to Reddit, Discord, Slack, LinkedIn or
Twitter. Given that student tools spread through Reddit and university Discords rather than through
Google, this image does more for reach than most of the on-page work.

- **1280 x 640 px**, PNG or JPG, under 1 MB
- Keep text well inside the middle: some clients crop to 2:1 and others to a rounded rectangle
- It should carry the app name, the one-line promise, and a real screenshot rather than only the icon

One of the Microsoft Store marketing images will likely crop to this cleanly.

---

## 4. Optional, in rough order of value

**Enable Discussions** (Settings → General → Features). A Q&A category absorbs the "how do I get my
token" and "does it work with my university" questions that otherwise arrive as issues, and
discussion threads get indexed, so real student questions become search entry points.

**Pin the repository** on the org profile so it is the first thing visitors see.

**Give the org a profile.** Create a repository named `.github` under `BrkBuilds` containing
`profile/README.md`, and it renders on `github.com/BrkBuilds`. Set the org avatar to the app icon.

**Link back from the website.** The site should link to the repository as prominently as the
repository links to the site. Two properties pointing at each other is worth more than either alone.

**Write real release notes.** Release pages are indexed separately from the repository. A release
titled "v2.0.2" with an empty body is a wasted page; one that names what changed is a page that can
rank on its own.

---

## 5. Developer identity

The organisation contact email is `brkbuilds1@gmail.com`, which is the address already used in
`SECURITY.md`, `CONTRIBUTING.md`, `DISCLAIMER.md` and the README, so the app now presents one
consistent identity.

Future commits are authored as `brkbuilds1@gmail.com` (set in this clone's git config).

**On the 476 historical commits authored as `birk.lykkeberg@gmail.com`:** they still carry that
address, and it is publicly visible in the commit history. Rewriting them is possible with
`git filter-repo`, but it changes every commit SHA, breaks every existing clone and fork, and does
not actually un-publish anything, because GitHub keeps the old objects reachable and third-party
mirrors already have them. The recommendation is to leave history alone and simply go forward under
the developer address.

If you want to reduce future exposure: **GitHub → Settings → Emails → Keep my email addresses
private**, and enable **Block command line pushes that expose my email**. Be aware this only affects
what GitHub shows and accepts going forward. It does not rewrite what is already there.
