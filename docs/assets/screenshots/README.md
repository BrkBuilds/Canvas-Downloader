# README screenshots

Drop app screenshots here, then uncomment the `<table>` block in the root `README.md`
under the "Screenshots" heading. The block is already written and points at these
exact filenames, so nothing else needs editing.

## What to capture

| Filename | Screen | What should be visible |
|---|---|---|
| `course-selection.png` | Step 1, course list | Several courses ticked, the search box in use, the "N of M selected" count |
| `quick-download.png` | Quick Download | All five preset cards in one shot |
| `sync-review.png` | Analyze, Review & Sync | A mix of file states, ideally New plus Update plus Ignored, so the seven-state model is visible |
| `progress.png` | A run in flight | The metrics row (transferred, speed, ETA) and the terminal log below it |
| `panopto-card.png` | Custom Download, Card 4 | The five recording outputs, Shortcut through Subtitles |
| `institution-picker.png` | Login | The institution directory open with a query typed |

## How to capture

- **1440 x 900 or wider.** Anything narrower and Streamlit stacks the columns, which
  makes the layout look worse than it is.
- **Use the app's own window**, not a browser tab, so the shot has no browser chrome.
- **Replace or blur real course names** if they identify you or your institution.
  A screenshot lives on the internet forever.
- **PNG**, and keep each file under about 500 KB. These are checked into the repository
  and every clone pays for them.

## Note on the Microsoft Store marketing images

Those are a different job. They are designed with text overlays and framing for a store
listing, which is right for the **social preview image**
(Settings, Social preview, 1280 x 640 - see `.github/REPO_SETUP.md`) and wrong for the
README body. Inside the README, a plain screenshot of the real interface is more
persuasive than a marketing composition, because it is evidence rather than a claim.
