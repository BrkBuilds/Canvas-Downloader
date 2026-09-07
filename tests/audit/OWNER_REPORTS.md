# Owner reports: defects seen in real use

Defects the product owner hit while USING the app on his own machines, written
down in the session they were reported. Kept separate from `AUDIT_FINDINGS.md`
on purpose: that file is written and re-fingerprinted by the live-audit harness
on every run, and a hand-written entry in it would either be clobbered or read
back as a harness finding. Nothing here came from a harness. Every entry says
what was CONFIRMED by reading the code and what is still a HYPOTHESIS awaiting a
repro, because this repo's rule is that an unreproduced cause is a pointer, not a
diagnosis.

Status vocabulary matches `AUDIT_FINDINGS.md`: `open`, `fixed`, `accepted`,
`wontfix`, `invalid`.

---

## Reported 2026-09-07, during the Store rename work

All four were reported together, and all four were **deliberately excluded from
v2.0.3**. That release exists only to make the MSIX `DisplayName` match the Store
listing name, under a certification deadline of 14 September. Bundling UI or auth
changes into the submission that has to pass would put the deadline at risk for
defects that are already live in 2.0.2 and make nothing worse by waiting. They
are the 2.0.4 list.

---

### 1. "See configuration" on Quick Download does not reflect what was chosen

**Status**: open
**Severity**: low
**Reported**: 2026-09-07, owner, from ordinary use
**Reproduced by Claude**: no

**Detail**: The `See configuration` expander on the Quick Download page shows a
configuration that does not match what the user selected on that same page.

**Where to look**: `ui/quick_download.py:1082` renders
`st.expander("See configuration")`. The badge markup is
`shared/components.py:3606` `render_config_summary_badges(settings, show_path)`,
and the Panopto column of it is fed through
`panopto/settings.py:518` `contract_to_ui_keys(contract)`.

**The question to ask first**, because it decides the whole shape of the fix: is
the panel reading the SAME settings dict the run will execute, or a preset
default that the page's own controls have since overridden? A summary built from
a different source than the executor is not a rendering bug, it is two sources of
truth, which is the defect class CLAUDE.md names first.

---

### 2. Custom Download: "See configuration" and "Change folder" get swallowed into the download phase card

**Status**: open
**Severity**: medium (cosmetic, but persistent and highly visible)
**Reported**: 2026-09-07, owner, seen once on his own PC
**Reproduced by Claude**: no

**Detail**: On Custom Download, after interacting with `Change folder` and
`See configuration` and then pressing the download button quickly, both elements
were absorbed INTO the download phase card, rendered underneath the live log and
greyed out. **There were no reruns during the download, so they never went away**
for the whole run.

**This is almost certainly the known Streamlit index-reconciliation family, not a
new bug.** The repository already documents the mechanism three times: a keyed
card is inherited by whatever element lands on its index, `addBlock` REUSES the
children of the block it replaces, and a container replacement that is not
isomorphic hands its slot to a sibling. See `.claude/rules/streamlit-ui.md` and
the completion-card entries. The distinguishing symptom here is the same one
those entries describe: the wrong parent adopts live children, and greying is the
new parent's styling applied to nodes that were never its own.

**Why the timing matters**: pressing download quickly is what makes the phase
card appear in the same run as elements the page had just mutated. That is the
race, and it is why it is hard to hit twice.

**Do not fix this by converting the elements to `st.empty()` or a fresh
container.** Both are recorded as the wrong tool inside a list-shaped region and
one of them caused a whole-page blank flash. Reproduce first, then count slots
and children.

---

### 3. Panopto switched OFF still produces a failure expander on the success screen

**Status**: open
**Severity**: low, but it is the one that annoys the owner most
**Reported**: 2026-09-07, owner
**Reproduced by Claude**: no

**Detail**: With Panopto switched off in Settings, downloading a course that has
Panopto content still shows a *"couldn't download panopto lecture recordings"*
expander on the SUCCESS completion screen. Nothing failed. The user turned the
feature off on purpose, so a failure panel is both wrong and irritating.

**The polite panel already exists and is already wired**, which is why this reads
as a duplicate rather than a missing feature.
`shared/components.py:2694` `render_panopto_disabled_notice()` is the third
member of the "deliberately left alone" family (size-skipped files, unpacked
archives): a quiet skip-panel that says recordings were not fetched because the
switch is off. It is called from `app.py:2804` for download mode and
`sync/completion.py:255` for sync mode, and it returns early when the switch is
on. That is exactly the "less invasive" treatment the owner asked for, and it is
shipped.

**HYPOTHESIS, not confirmed**: the generic failed-files expander at
`shared/components.py:2148` (*"We couldn't download these files after
retrying."*) is a SEPARATE panel, and Panopto or LTI media items are still
landing in its list even when the switch is off, so both panels render. The
category label `'LTI/Media Stream'` at `shared/components.py:1670` is where such
an item would be classified.

**The repro to run**: switch Panopto off, download one known Panopto course, and
capture the completion screen. If BOTH panels are present, the fix is to stop
filing Panopto/LTI items as failures when the switch is off, not to add another
notice. If only the failure panel is present, the disabled notice is being
suppressed and the question is why `panopto_disabled_courses(mode)` returned
empty.

---

### 4. Today's files runs on a session that was never CONFIRMED, and reports one amber notice per course

**Status**: open
**Severity**: medium, and it is the one with real user impact
**Reported**: 2026-09-07, owner, from two separate incidents on two machines
**Root cause**: CONFIRMED by reading, on the auto-sync precondition. The second
incident's classification step is still a hypothesis.

**The two incidents**

- **Slow laptop, wifi still connecting** (2026-09-05). Daily auto-sync fired
  correctly, then produced a cascade of amber notices, one after another. Once
  wifi came up the app recovered and downloaded.
- **Revoked token, good internet** (2026-09-07). The app went straight into
  Today's files and started searching for files to download. Every course fetch
  failed and spawned its own amber notice under the search/download card.
  **His name was missing from the login area**, so the app already had evidence
  the token was dead before Today's began.

**CONFIRMED root cause**: `core/auto_sync.py:72` `should_auto_sync()` gates on
exactly three things - the auto-sync setting, `last_auto_sync_date` against
`logical_today()`, and `resolve_today_pairs()` being non-empty. **There is no
precondition on whether the saved session was actually confirmed against Canvas
this launch.**

**Why an unconfirmed session exists at all, and why that part is CORRECT**:
`ui/auth.py` restore calls `CanvasManager.validate_token()`. On success it sets
`is_authenticated` AND `user_name`. On failure it splits: `is_auth_error(msg)`
routes to the login page for a fresh token, and **anything else restores
OPTIMISTICALLY** - `is_authenticated = True`, `user_name` never set - so a
network blip does not strand a previously verified session behind a login wall.
The code documents this as *"the single most important robustness property of the
login path for users on unreliable or high-latency networks"*, and it is right.
Do not fix this by making restore pessimistic.

**The gap is that Today's auto-sync cannot tell the two apart**, and it is the
one caller that must, because it runs headless, immediately, once per course,
with a visible notice per failure. Incident 1 is that exact path.

**The discriminator already exists and costs nothing**: on the optimistic branch
`user_name` is never set, so `is_authenticated and not user_name` IS "signed in
but unconfirmed this launch". A named flag set at the two decision sites would be
cleaner than inferring it from a display string, and writing the verdict once is
this repo's standing rule.

**Still a hypothesis for incident 2**: with a genuinely revoked token on a good
connection, `is_auth_error(msg)` should have matched and sent him to the login
page. He landed in Today's instead, which is the optimistic branch, so either
that classifier did not recognise this revocation message or something else set
`is_authenticated`. **Reproduce by revoking a token and relaunching**, and read
what `validate_token()` actually returned before changing the classifier. A
classifier fixed against a guessed message is a classifier that still cannot say
no.

**Second, independent defect in the same report**: N failing courses produce N
amber notices. One notice for the run, naming the count, is the right shape, and
it is worth fixing even if the gating above lands, because a slow network can
still fail some courses mid-run.
