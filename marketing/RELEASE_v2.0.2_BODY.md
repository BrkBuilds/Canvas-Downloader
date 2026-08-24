Canvas Downloader batch-downloads your Canvas course materials to your own computer and keeps them in sync. It runs entirely on your machine, needs nothing but your own Canvas account, and is free.

2.0.2 makes the app faster everywhere, adds a searchable directory of 4,750+ verified Canvas schools to the login screen, and fixes several bugs that could cost you work. If you are upgrading, the fixes under **Fixed: your files** are the ones worth reading.

## New

**Find your university on the login screen.** A searchable directory of 4,750+ verified Canvas institutions now sits beside the URL field. Pick yours and the address fills itself. It opens on your own country, and search ignores accents, so `kobenhavn` finds Københavns Universitet and `goteborg` finds Göteborg. It is a shortcut and never a gate: if your school is not listed, type the address exactly as before.

**Save a lecture as a link, not just a file.** A new Panopto output writes a shortcut straight to the recording (`.url` on Windows, `.webloc` on macOS). It costs no bandwidth, no disk and no time, and it takes you back to the lecture with the slides, the screen capture and Panopto's own search still attached. A companion to the offline copy, not a replacement for it.

**Turn Panopto off completely.** One switch in Settings. Off means no institution lookup, no discovery, no acceptable-use dialog and no recordings in any download or sync. It skips the work and not just the result, which on a university with no Panopto saves dozens of pointless handshakes per run. Your per-folder settings are preserved rather than erased, so switching it back on resumes exactly what you had chosen.

**Name your own courses.** A saved course-folder pair can be given a name that means something to you, and it shows up everywhere that pair appears, including retroactively in your sync history. The name follows the pair when you move the folder.

**One place for saved pairs and groups.** Saved pairs, groups and daily-sync membership now live in a single store keyed to a stable id instead of a folder path. Moving a folder keeps its name, deleting and re-adding a pair no longer resurrects the old one, and a change in the hub shows up on the Today page immediately.

**A time estimate that means something.** Scanning, downloading, converting and transcribing all estimate through one model that learns from the run in front of it. A course that opens with 26 zero-byte shortcuts used to show "Estimating" for 90 seconds and then a figure roughly seven times the truth.

**A step tracker across both flows.** Download and sync each show you where you are, and you can click back to a step you have already passed. Quick Sync shows the Review step struck through, because it genuinely skips it.

**Help text you can turn off.** Settings > Show help text hides the explanatory cards and captions once you know the app. Nothing operational is hidden: errors, counts, empty states and the reason a control is unavailable all stay.

## Faster

**Pages open roughly four times faster.** Click to usable went from a measured 2046 ms to 487 ms (median). The course list is no longer fetched while the page renders, and switching modes no longer throws that list away.

**Transitions no longer flicker.** The loading overlay used to lift a median 1.5 seconds after the page had finished, and up to 7.9 seconds. During a long run it covered the app's own progress screen for a flat 8 seconds. Visible churn during a transition is down from a mean of 351 ms to 53 ms.

**Dialogs no longer flash.** Opening any dialog briefly brightened the whole window to twice its settled brightness. That was Streamlit's own two-layer backdrop. It is one layer now, and the entrance is smooth.

## Fixed: your files

- **A file Canvas listed could be missing from the review screen entirely.** When two files in a course shared one internal filename, one of them was dropped from every category: not new, not up to date, not deleted. That is now impossible by construction, and it is asserted over 500 generated course states.
- **Re-downloading a course could remove the protection on a file you had edited.** The record of what was originally downloaded was being rewritten from whatever was on disk, so a later sync saw your edited file as untouched and was free to overwrite it.
- **A converted file could be re-offered as "deleted" for ever.** 62 of 63 Office conversions left their tracking pointing at the source they had just replaced, which showed up as "63 Deleted locally" on the next sync.
- **A half-written PDF could replace your only copy of a document.** The check that decides whether the original may be deleted now requires a complete file, not just a plausible-looking start.
- **Word, Excel or PowerPoint could be closed with your unsaved document still in it.** Two separate causes: a failed conversion closed whatever document happened to be in front, and the app could mistake your own Office window for the hidden one it had started.
- **Your saved login could be lost by a failed save.** On macOS the Keychain deletes before it writes, so a refused write left nothing behind.
- **Course files kept in iCloud with Optimize Mac Storage are supported**, and a sync no longer pulls a whole course back down just to look at it.

## Fixed: macOS

- **After an app update the window could sit empty for 30 to 90 seconds.** macOS raises a Keychain prompt when the app signature changes, and it was blocking the page from rendering at all, with no explanation anywhere. The app now explains the dialog before it appears and signs itself in once you answer. It also tells you to choose **Always Allow**: measured, plain *Allow* leaves the prompt coming back on every single launch, for ever.
- **Office conversion is quieter and cleaner.** Apps you already had open are never quit, apps this app opened are, and its temporary entries no longer pile up in Office's Recent list.
- **It no longer asks for Accessibility permission.** It never needed it, and it is the worst prompt macOS has: there is no Allow button, and the wording says "control this computer".
- Course folders on external drives, on case-sensitive volumes, and with Danish or other accented filenames are all handled correctly.

## Licence

This release relicenses Canvas Downloader from MIT to **GPL-3.0-or-later**. If you are just using the app, nothing changes: it is still free, still open source, and still does everything it did before. If you have forked or reused the code, the new terms apply from this version onward.

## Download

| Platform | File | Requirements |
|---|---|---|
| Windows | `Canvas_Downloader_v2.0.2_Windows.exe`, or the [Microsoft Store](https://apps.microsoft.com/detail/9n1dwwvrq5wc) | Windows 10 or 11, 64-bit |
| macOS | `Canvas_Downloader_v2.0.2_macOS.dmg` | Apple Silicon, macOS 14 or newer |

The direct downloads are unsigned, so Windows shows a SmartScreen warning and macOS shows a Gatekeeper warning. Code-signing certificates cost money every year on both platforms, and keeping the app free means not buying them. The Microsoft Store build is signed and shows no warning.

Setup guides walk through those dialogs for your exact version: [Windows](https://canvasdownloader.app/win-setup.html) and [macOS](https://canvasdownloader.app/mac-setup.html).

## Links

[Website](https://canvasdownloader.app/) · [Full guide](https://canvasdownloader.app/guide.html) · [How it works](https://canvasdownloader.app/engine.html) · [Privacy](https://canvasdownloader.app/privacy.html) · [Report a problem](https://github.com/BrkBuilds/Canvas-Downloader/issues)

Free, open source, GPL-3.0 licensed. Nothing is uploaded anywhere: it runs entirely on your own machine and reads only what your own Canvas account can already open.
