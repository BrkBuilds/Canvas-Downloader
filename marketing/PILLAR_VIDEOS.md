# Pillar videos

How to add, replace, re-cut or remove one of the six looping demo clips on the
homepage, without undoing a measurement someone already paid for. Read this
alongside `SITE_RUNBOOK.md`, which covers the site around them.

Everything below was measured on 2026-08-25 unless it says otherwise.

---

## 1. What a pillar video actually is

Six things have to agree, and nothing warns you when one is missed. Four of
them live in `docs/index.html`.

| # | Piece | Where | If it is wrong |
|---|---|---|---|
| 1 | the `.mp4` | `docs/assets/` | broken slot |
| 2 | the poster `.webp` | `docs/assets/` | blank slot while the clip downloads |
| 3 | the `<video>` element | `index.html`, in that pillar's `.pillar-vis` | see the attribute rules in section 4 |
| 4 | the `VideoObject` node | `index.html`, the one `ld+json` `@graph` | schema that lies is worse than no schema |
| 5 | `<lastmod>` for `/` | `docs/sitemap.xml` | the change looks stale to crawlers |
| 6 | this file | here | the next person re-derives all of it |

Do not write the element from memory. Copy a neighbour and change the values:

```html
<video class="expandable-video" preload="none" width="1920" height="1080"
  data-poster="assets/poster-SLUG.webp"
  data-src="assets/SLUG.mp4"
  autoplay loop muted playsinline aria-label="ONE SENTENCE, see 4.5"
  style="width: 100%; height: auto; border-radius: var(--rad-l); border: 1px solid var(--border); display: block; box-shadow: 0 16px 40px rgba(0,0,0,0.2);"></video>
```

`autoplay loop muted playsinline` is the whole reason it loops silently on
every device. `muted` is not optional: without it no browser will autoplay.

---

## 2. The encoding recipe

One command. `ffmpeg` 8.x from winget is on PATH; the binary bundled with
`imageio-ffmpeg` works too.

```bash
ffmpeg -y -i "SOURCE.mp4" \
  -vf "scale=1920:-2:flags=lanczos" \
  -c:v libx264 -preset veryslow -crf 22 -profile:v high \
  -x264-params "aq-mode=3:psy-rd=0.6,0.15:deblock=-1,-1" \
  -pix_fmt yuv420p -g 60 -movflags +faststart -an \
  "docs/assets/SLUG.mp4"
```

Every flag is a decision, not a default:

- **`scale=1920`** because the expand modal is `max-width: 1200px`, so 1920
  still has headroom there, and the inline slot is only about 476 CSS px.
  `-2` keeps the height even, which yuv420p requires. Sources here are 2560
  wide, so this is a clean 0.75 downscale.
- **`lanczos`** for text. The default bilinear softens small UI type.
- **`crf 22`** is transparent for this content, and that was checked by eye
  rather than by a number: a 1:1 crop of the hardest text in the set (the
  Panopto file list with its small `TXT, SRT` tags) against a lossless 1920
  downscale is indistinguishable. The sweep is in section 6.
- **`aq-mode=3`** biases bits toward dark areas. The whole app is a dark
  theme, so this is the parameter that matters most here.
- **`veryslow`** costs a few minutes once and nothing afterwards.
- **`-an`** because the element is `muted` forever. Audio is dead weight.
- **`+faststart`** puts the moov atom first so playback can begin before the
  file has finished downloading. Without it a deferred video stalls.
- **No `-level`.** Constraining to level 4.0 dropped x264 to one reference
  frame and cost 10% size, for compatibility no device made this decade
  needs.

Then the poster:

```bash
ffmpeg -y -i "docs/assets/SLUG.mp4" \
  -vf "select=eq(n\,FRAME),scale=1280:-1" -frames:v 1 \
  -c:v libwebp -quality 86 "docs/assets/poster-SLUG.webp"
```

**WebP at 1280, not JPEG at 960.** Measured on the same frame: 1280 WebP q86
is **36 KB** against 960 JPEG q3 at **47 KB**. Larger for search, smaller on
the wire, and the site already ships its hero as WebP, so this is not a new
dependency.

---

## 3. Replace, add, remove

### Replace a clip

1. Encode the new `.mp4` and its poster (section 2). **Use a new filename.**
   That is not tidiness: if the dimensions change, a cached copy of the old
   file disagrees with the `width`/`height` you just declared, and that is
   layout shift. A new name makes a stale cache impossible.
2. Point `data-src`, `data-poster`, `width` and `height` at it, and rewrite
   the `aria-label` to describe what the new clip shows.
3. Update the `VideoObject`: `contentUrl`, `thumbnailUrl`, `width`, `height`,
   `duration`, `uploadDate`. Read the first four out of `ffprobe`; never type
   them from memory.
4. `git rm` the old `.mp4` and poster. Check nothing else references them
   first: `grep -rl "OLD-NAME" docs/ scripts/ tests/`. Historical reports
   under `tests/audit/` do not count and must not be edited.
5. Bump `<lastmod>` for `/` in `docs/sitemap.xml`.
6. Verify (section 5).

### Add a pillar

Everything above, plus a new `VideoObject` in the `@graph`. **Keep the graph
in page order** so the next person can diff the page against the schema by
reading straight down.

Adding a video adds nothing to the page load, because posters and sources are
both deferred (4.1). The cost of a seventh pillar is bandwidth for people who
scroll to it, not LCP for everyone.

### Remove a pillar

Delete the element, delete its `VideoObject`, `git rm` both assets. If it was
the last `.expandable-video`, see the last note in section 7.

### Re-cut without re-recording

`crop` and `scale` both force a re-encode, so quality is capped by the file
you start from. Re-encoding a 186 kbps source at CRF 19 spent 1031 KB
faithfully preserving its own compression artifacts and looked no better than
CRF 24 at 755 KB. **When you must re-encode an already-compressed asset,
measure generation loss against a losslessly cropped copy of that asset**,
not against a pristine original you do not have:

```bash
ffmpeg -y -i in.mp4 -vf "crop=W:H:X:Y" -c:v libx264 -qp 0 -preset ultrafast -an ref.mp4
ffmpeg -i out.mp4 -i ref.mp4 -lavfi "[0:v][1:v]ssim" -f null -
```

---

## 4. The rules, and the measurement behind each

### 4.1 Posters are deferred, and must stay deferred

**A poster cannot be lazy-loaded.** There is no `loading="lazy"` for one, so
every poster on the page is fetched eagerly whatever `preload` says. Going
from four demo videos to six therefore put two more images in front of the
hero image, which IS the LCP element, and mobile LCP went **3476 to 3984 ms**.

Both the source and the poster now live in `data-` attributes and are attached
by the IntersectionObserver bridge at the bottom of `index.html`:

| | Before | After |
|---|---|---|
| Mobile LCP (390px, 4x CPU, 1.6 Mbps) | about 3480 ms | **2836 ms** |
| CLS | 0.0013 | 0.0013 |
| Posters and videos fetched on load | 4 | **0** |

Better than before the two videos were added, because the page now fetches
zero posters instead of four.

**Attaching the poster in the same tick as the source loses nothing.** The
poster's job is to cover the *video download*, not the *scroll approach*. At
about 36 KB against a 1 to 2 MB clip it still wins by a wide margin and still
fills the slot for the whole download.

### 4.2 `width` and `height` are mandatory

They are what makes 4.1 safe. The poster used to be what gave the element its
intrinsic aspect ratio; deferring it without the attributes collapses every
slot to the 300x150 UA default and the page shifts as they load. The inline
style must therefore also carry `height: auto`, or the `height` attribute wins
the layout and the video renders 1080px tall.

### 4.3 The clip must be edge to edge

These recordings are of app windows that already have **their own rounded
corners and drop shadow**. If the file has dead space around that window, our
`border-radius` plus `border` draws a second frame around the first one, with
black in between. That shipped on pillar 1 (1800x1440, window at x 20-1779,
y 24-1410) and reads as sloppy at a glance.

`cropdetect` will not find it, because it only looks for pure black and the
padding here is the window's own shadow. Measure the real margins:

```python
# luma of every edge line; a dead margin is an edge that is essentially black
L = next(x for x in range(w) if a[:, x].max() > 12)
R = next(x for x in range(w) if a[:, w-1-x].max() > 12)
T = next(y for y in range(h) if a[y, :].max() > 12)
B = next(y for y in range(h) if a[h-1-y, :].max() > 12)
```

Anything above about 3 is a dead margin. Crop it out before encoding. Check
the bounds at several timestamps first: a clip that zooms or resizes cannot
take a static crop.

### 4.4 Filenames are query-shaped

`download-transcribe-panopto-lectures.mp4`, not `Panopto_Demo.mp4`. The
filename is a ranking signal for video and image search and it costs nothing
to spend well. Lowercase, hyphens, describe the task a student would type.

### 4.5 Every clip carries an `aria-label`

A `<video>` has no `alt`. When a still image is replaced by a clip, its `alt`
text has to survive as the `aria-label` or the description is simply lost.
One sentence, concrete, describing what happens in the clip.

### 4.6 Poster frames are CHOSEN, and eyeballed

Never sample at a fixed percentage. `FINDINGS.md` records why: a 15% sample
once landed on a Windows file dialog whose OneDrive sidebar showed a legible
personal name, and a `thumbnailUrl` **actively submits an image for indexing**,
which is broader and more persistent than a frame inside a looping clip.

Pick the frame that is the pillar's promise in one picture, then **look at it
at full size before shipping**. Reject anything showing a file dialog, a
browser window, an email address, a personal folder path, or a notification
from another app. Course names and course codes are institutional and already
public across the site, but that is the operator's standing call and not a new
one to make quietly.

Contact sheet for choosing:

```bash
ffmpeg -y -i clip.mp4 -vf "select='not(mod(n\,50))',scale=640:-2,tile=4x3" -frames:v 1 grid.png
```

### 4.7 The schema must state the truth

`width`, `height` and `duration` come from `ffprobe`, with `duration` rounded
to the nearest second (`PT30S`). A `VideoObject` that misstates a duration is
worse than no `VideoObject`.

---

## 5. How to verify, every time

Serve `docs/` and drive it. Use an independent Playwright instance; the MCP
browser may be held by another session.

```bash
cd docs && python -m http.server 8777
```

**Headless Chromium suppresses autoplay**, so launch with
`--autoplay-policy=no-user-gesture-required` or every clip reports
`paused=true` and you will chase a bug that is not there. The control that
tells you it is the harness and not your change: the clips you did *not*
touch report `paused=true` as well.

Check, in this order:

1. **Every clip loads and loops.** Read `currentSrc`, `poster`, `loop`,
   `muted`, `paused`, `readyState` off each `.expandable-video`. Prove the
   loop rather than trusting the attribute: seek to `duration - 0.4` and watch
   `currentTime` wrap back toward zero.
2. **No leftover `data-src` or `data-poster`** after scrolling the whole page.
3. **Zero page errors and zero 4xx.** Listen on `pageerror` and `response`.
4. **Box heights are identical before and after load** (4.2).
5. **Core Web Vitals on a mobile profile, A/B against the pre-change site.**
   Copy `docs/` out of git (`git archive HEAD docs | tar -x -C DIR`), serve it
   on a second port, and measure both under the same throttle. Desktop numbers
   on this site are flattering and have been reported as a clean bill of
   health while the mobile number sat in the POOR band. The profile is in
   `SITE_RUNBOOK.md` section 6.
6. **Look at it.** Screenshot each changed `.pillar-row` at
   `device_scale_factor=2`, and again at 390px wide. Rule 4.3 is invisible in
   code review and obvious in one screenshot.
7. `python -m pytest tests/ -q -k "website or repo_urls"`.

---

## 6. Decisions taken. Do not re-litigate without new measurements.

### AV1 was measured and declined

At matched quality it is consistently about 36% smaller on this content:

| encode | size | SSIM |
|---|---|---|
| x264 CRF 20 | 2083 KB | 0.999226 |
| x264 CRF 22 | 1773 KB | 0.998970 |
| x264 CRF 24 | 1517 KB | 0.998657 |
| **SVT-AV1 CRF 38** | **1324 KB** | 0.999237 |
| **SVT-AV1 CRF 42** | **1129 KB** | 0.998964 |

(30s 1920x1080 clip, SSIM against a lossless 1920 downscale.)

Declined because shipping it needs a codec fallback chain in the defer bridge,
and a pillar video that fails to decode is a far worse outcome than a larger
file that always plays. The videos are deferred, so the saving would not reach
LCP either. If it is ever revisited: `<source>` order or a `canPlayType`
probe, H.264 last, and the poster must still render if every source fails.

### H.264, 1920 wide, one file per clip

No `<source>` chain, no responsive variants. Six clips is not enough content
to justify the machinery, and every extra file is another thing that can go
missing without a symptom.

### No-JS visitors now see an empty slot

They used to see the poster. This is the accepted cost of 4.1. It was already
a dead video for them (the source has been JS-gated since 2026-08-20), so what
was lost is a still image, not functionality.

**The obvious fix does not work.** Hiding the video under `html:not(.js)` and
showing a `<noscript><img>` collides with the old-WebKit path: `html.js` is
set only when `IntersectionObserver` exists, and when it does not the bridge
deliberately loads *every* clip eagerly. So `html:not(.js)` would hide videos
that are working. Recovering the still needs a second, unconditional flag in
the head script, which is more machinery than the audience justifies.

---

## 7. Traps, each paid for once

- **`docs/index.html` is CRLF.** A multi-line anchor written with `\n` never
  matches and reads as a missing guard. Read and write with `newline=''` and
  build replacements with `\r\n`.
- **Editing the `ld+json` `@graph` by string anchor: the 6-space `      },` is
  a substring of the 8-space `        },` that closes `publisher`.**
  `str.find` will happily cut a node in half there and leave an orphaned
  `"about"` block, and the only symptom is a `JSONDecodeError` a hundred lines
  further down. Anchor with the leading newline included, and **always
  `json.loads` the block afterwards**. That check is what caught it.
- **Assert your replacement count.** Every patch script used here asserts
  `src.count(old) == 1` before replacing. A silent zero-match "success" is the
  characteristic failure of editing this file by script.
- **`cropdetect` only sees pure black.** See 4.3.
- **A distorted A/B tells you nothing.** Stacking two frames of different
  aspect ratios with `scale=W:H` silently squashes them and can make a correct
  crop look wrong. Pad to a common size; never scale to one.
- **`.expandable-img` is now dead.** No element on the page uses it, so the
  CSS, the modal branch and its JS loop iterate an empty NodeList. Harmless,
  but it now looks live. If a still image is ever added back to a pillar it
  already works; if not, it is a small cleanup.

---

## 8. Current inventory

| # | Pillar | File | Size | Duration | Bytes |
|---|---|---|---|---|---|
| 1 | Download | `download-all-canvas-courses-to-folders.mp4` | 1760x1388 | PT12S | 755 KB |
| 2 | Quick Sync | `quick-sync-new-canvas-files.mp4` | 1920x1026 | PT17S | 1096 KB |
| 3 | Daily Auto-Sync | `daily-auto-sync-canvas-files.mp4` | 1920x1026 | PT19S | 1368 KB |
| 4 | AI Optimization | `convert-canvas-files-for-ai.mp4` | 1920x1080 | PT30S | 1774 KB |
| 5 | Sync Review | `Sync_Review_Demo.mp4` | 1920x1080 | PT29S | 2648 KB |
| 6 | Lecture Recordings | `download-transcribe-panopto-lectures.mp4` | 1920x1080 | PT33S | 2079 KB |

Total with posters: **9.72 MB, all of it deferred, zero bytes fetched on page
load.**

Pillar 5 is the last one on the old convention: a `.jpg` poster at 960 wide,
and a filename that is not query-shaped. It was left alone because re-encoding
a clip nobody has complained about is churn. Fold it in the next time that
clip is re-recorded.

Source recordings live outside the repo, under
`G:\6 projekter\Canvas Downloader\ScreenRecordings\`. They are deliberately
not tracked: the masters are 2560 wide and the raw sessions run to tens of
minutes.
