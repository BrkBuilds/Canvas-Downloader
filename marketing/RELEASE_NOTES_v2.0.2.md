# v2.0.2 release notes — factual scaffolding

**This is not final copy.** It is *what actually changed*, verified against the
`v2.0.1` tag rather than assembled from memory, grouped the way a user would
notice it. The voice, the ordering and what to cut are yours.

568 commits since `v2.0.1` (11 July 2026). Only user-visible changes are listed;
audit, test and documentation work is left out.

---

## Verify before you publish

Two things this file exists to stop you getting wrong, because both have
happened here before:

1. **Name the asset that is actually attached.** The Windows build emits
   `Canvas_Downloader_Setup_2.0.2.exe`; the release asset is
   `Canvas_Downloader_v2.0.2_Windows.exe`. v2.0.1's notes named the build output,
   not the attachment.
2. **Every link must resolve.** v2.0.1, v2.0.0 and v1.0.0 all shipped with dead
   `github.io` links — four hard 404s on v2.0.1 alone, including the headline
   link and the Mac setup guide. Those are fixed now; do not copy from an old
   draft. Live targets: `https://canvasdownloader.app/`, `/guide.html`,
   `/mac-setup.html`, `/win-setup.html`, `/privacy.html`, and
   `https://github.com/BrkBuilds/Canvas-Downloader/issues`.

---

## A correction to carry into the copy

`tests/audit/MAC_AUDIT_PROMPT.md` says "the whole Panopto subsystem shipped"
since v2.0.1. **That is too strong** — checked against the tag, `panopto/runner.py`,
discovery and transcription were all *already in v2.0.1*, as was the Today page.
What is genuinely new in Panopto for 2.0.2 is the **Shortcut output** and the
**global on/off switch**. Saying "Panopto is new" would be a claim a returning
user can immediately falsify.

---

## New in 2.0.2

**Find your university on the login screen.** A searchable directory of **4,750+
verified Canvas institutions** sits beside the URL field; pick yours and the
address fills itself. It opens on your own country, and search is accent-folded,
so `kobenhavn` finds Københavns Universitet and `goteborg` finds Göteborg. Every
entry was verified to be a live Canvas host. It is a shortcut and never a gate —
schools that are not listed work exactly as before, by typing the address.

**Save a lecture as a link, not just a file.** A new Panopto output writes a
shortcut (`.url` on Windows, `.webloc` on macOS) straight to the recording. It
costs no bandwidth, no disk and no time, and it takes you back to the lecture
with the slides, the screen capture and Panopto's own search still attached — a
companion to the offline copy, not a replacement for it.

**Turn Panopto off completely.** One switch in Settings. Off means no
institution lookup, no discovery, no acceptable-use dialog and no recordings in
any download or sync — and it skips the *work*, not just the result, which on a
university with no Panopto saves dozens of pointless handshakes per run. Your
existing per-folder settings are preserved, not erased, so switching back on
resumes exactly what you had chosen.

**Name your own courses.** Saved course-folder pairs can be given a name that
means something to you, and it now shows everywhere that pair appears —
including retroactively in sync history. The name follows the pair when you move
the folder.

**One place for saved pairs and groups.** Saved pairs, groups and daily-sync
membership now live in a single store keyed to a stable id rather than a file
path. Moving a folder keeps its name; deleting and re-adding a pair no longer
resurrects an old one; a change in the hub shows up on the Today page
immediately.

**A time estimate that means something.** Every phase — scanning, downloading,
converting, transcribing — now estimates through one model that learns from the
run in front of it. A course that opens with 26 zero-byte shortcuts used to show
"Estimating" for 90 seconds and then a figure roughly seven times the truth.

**A step tracker across both flows.** Download and sync each show where you are,
and you can click back to a step you have already passed. Quick Sync shows the
Review step struck through, because it genuinely skips it.

**Help text you can turn off.** Settings → Show help text hides the explanatory
cards and captions once you know the app, without hiding anything operational —
errors, counts, empty states and the reason a control is unavailable all stay.

---

## Faster

**Pages open roughly four times faster.** Click to usable went from a measured
**2046 ms to 487 ms** (median). The course list is no longer fetched while the
page renders, and a navigation no longer throws that list away — which is why
switching modes used to cost about a second of Canvas round-trips every time.

**Transitions no longer flicker.** The loading overlay used to lift a median
1.5 s after the page was finished, and up to 7.9 s; during a long run it covered
the app's own progress screen for a flat 8 s. Visible churn during a transition
is down from a mean of 351 ms to **53 ms**.

**Dialogs no longer flash.** Opening any dialog briefly brightened the whole
window to twice its settled brightness. That was Streamlit's own two-layer
backdrop; it is now one layer and the entrance is smooth.

---

## Fixed — your files

These are the ones worth reading, because each could cost you work.

- **A file Canvas listed could be missing from the review screen entirely.**
  When two files in a course shared one internal filename, one of them was
  dropped from every category — not new, not up to date, not deleted. It is now
  impossible by construction: every file Canvas offers must land somewhere, and
  that is asserted over 500 generated course states.
- **Re-downloading a course could remove the protection on a file you had
  edited.** The record of what was originally downloaded was being rewritten
  from whatever was on disk, so a later sync saw your edited file as untouched
  and was free to overwrite it.
- **A converted file could be re-offered as "deleted" for ever.** 62 of 63
  Office conversions left their tracking pointing at the source they had just
  replaced, which showed up as "63 Deleted locally" on the next sync.
- **A half-written PDF could replace your only copy of a document.** The check
  that decides whether the original may be deleted now requires a complete file,
  not just a plausible-looking start.
- **Word, Excel or PowerPoint could be closed with your unsaved document in it.**
  Two separate causes: a failed conversion closed whatever document happened to
  be in front, and the app could mistake your own Office window for the hidden
  one it started and force-close it.
- **Your saved login could be lost by a failed save.** On macOS the Keychain
  deletes before it writes, so a refused write left nothing behind.
- **Course files kept in iCloud with "Optimize Mac Storage" are supported**, and
  a sync no longer pulls the whole course back down to look at it.

---

## Fixed — macOS

- **After an app update the window could sit empty for 30–90 seconds.** macOS
  raises a Keychain prompt when the signature changes, and it was blocking the
  page from rendering at all — with no explanation, and no explanation on the
  login screen afterwards either. The app now explains the dialog before it
  appears and signs itself in once you answer. It also tells you to choose
  **Always Allow**: measured, plain *Allow* leaves the prompt returning on every
  single launch, for ever.
- **Office conversion is quieter and cleaner**: apps you already had open are
  never quit, apps the app opened are, and its temporary entries no longer pile
  up in Office's Recent list.
- **The app no longer asks for Accessibility permission.** It never needed it,
  and it is the worst prompt macOS has — no Allow button, and the wording says
  "control this computer".
- Course folders on external drives, on case-sensitive volumes, and with Danish
  or other accented filenames are handled correctly.

---

## Still true, and stated plainly

The direct downloads are **unsigned**, so Windows shows SmartScreen and macOS
shows a Gatekeeper warning. Keeping the app free means not paying Apple's
$99/year. The **Microsoft Store** build is signed and shows no warning. The
`mac-setup.html` guide walks through the macOS dialogs for your exact version.

---

## Suggested asset table

| Platform | File | Requirements |
|---|---|---|
| Windows | `Canvas_Downloader_v2.0.2_Windows.exe` — or the [Microsoft Store](https://apps.microsoft.com/detail/9n1dwwvrq5wc), no SmartScreen warning | Windows 10/11, 64-bit |
| macOS | `Canvas_Downloader_v2.0.2_macOS.dmg` | Apple Silicon, macOS 14+ |

*Confirm both filenames against the attached assets before publishing.*
