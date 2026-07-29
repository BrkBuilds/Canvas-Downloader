"""
Time-remaining estimation - the single ETA model for every phase of the app.

Why this module exists
──────────────────────
The original ETA was ``remaining_mb / (downloaded_mb / elapsed)``. Three things
made that unusable on a real Canvas course:

1. **It is blind to anything that is not a byte.** A course that starts with 26
   Pages / ExternalUrl shortcuts / secondary-content files transfers *zero*
   bytes for the first minute-and-a-half, so ``speed`` stayed 0 and the cell
   read "Estimating" the whole time - at exactly the moment a user most wants a
   number. Those 26 items were not free; they cost API round-trips.
2. **The speed it divided by was a cumulative average since run start**, which
   is diluted by every pause, every rerun and the whole zero-byte phase. A run
   genuinely moving at 5 MB/s reported 0.7 MB/s, so the first real ETA it
   printed (20:34) was roughly 7x the truth.
3. **Progress and ETA disagreed by construction** - the bar is file-count based
   (42%) while the ETA was byte based (3.2% of bytes done).

The model
─────────
Work is two-channel: a **unit** channel (files, recordings, courses - anything
whose per-item cost is dominated by fixed overhead) and a **byte** channel
(actual transfer). Cost is assumed linear and additive:

    seconds ≈ unit_cost · units_remaining  +  byte_cost · MB_remaining

``unit_cost`` and ``byte_cost`` are fitted online by weighted, non-negative,
ridge-regularised least squares over a sliding window of recent work. The fit
self-calibrates: in a shortcut-only stretch every observation has ``db = 0`` so
only ``unit_cost`` moves; while a large PDF streams, only ``byte_cost`` moves.
Neither channel has to be guessed by hand, and neither can starve the other.

Three details do the heavy lifting:

* **Observations are bucketed into ~2 s bins, not sampled per event.** Fitting
  per event is the obvious approach and it is wrong: with 0.25 s repaints, a
  bucket that completes one file has ``dt = 0.25`` regardless of how long the
  file really took, so the fit reads ~0.25 s/file when the truth is 0.75. A
  coarse bin makes the cost identifiable because idle time lands in the same
  bin as the work it belongs to.
* **Unexplained wall-clock is recycled as a stall fraction.** A bin with no
  progress contributes nothing to the normal equations (every product is zero),
  so pure dead time - API discovery, rate-limit backoff - would otherwise be
  invisible. We compare the window's real elapsed time against what the fitted
  costs predict and inflate the estimate by that ratio.
* **Priors fade per channel, so an ETA appears immediately.** Each channel
  carries a pseudo-observation whose weight decays as *that channel* accrues
  real evidence. At t=0 the estimate is entirely prior ("~3:11"); by the time
  the first megabytes land it is entirely measured. The UI never has to say
  "Estimating" once totals are known - it says "~" instead, which is honest
  about the uncertainty without withholding the number.

Discontinuities (Streamlit reruns between courses, the post-processing phase,
a modal) are detected by gap length and dropped rather than counted as stall -
otherwise every course boundary would inflate the next course's estimate.

The module is deliberately dependency-free (no streamlit, no numpy) so it can
be unit-tested directly and imported from the engine, the converters and the
Panopto runner alike.
"""

from __future__ import annotations

import math
import time as _time
from collections import deque
from dataclasses import dataclass

MB = 1024.0 * 1024.0

# ── Defaults ────────────────────────────────────────────────────────────────
# Starting guesses, used only until real evidence replaces them (see the
# per-channel prior decay in ``_solve``). They are deliberately middle-of-the-
# road for a university network rather than optimistic.
DEFAULT_UNIT_SEC = 0.40          # seconds of fixed overhead per item
DEFAULT_BYTE_RATE = 4.0 * MB     # bytes/second of sustained transfer

# Sanity rails. A pathological window (one 900 MB file finishing in one bin)
# must never be able to project an hour of work as three seconds, or vice versa.
MIN_UNIT_SEC = 0.0
MAX_UNIT_SEC = 180.0             # 3 min/item covers Office conversions + transcription
MIN_BYTE_RATE = 16.0 * 1024.0    # 16 KB/s
MAX_BYTE_RATE = 1500.0 * MB      # local-disk-speed ceiling

BUCKET_SEC = 2.0                 # observation bin width (see module docstring)
WINDOW_SEC = 75.0                # how far back the fit looks
HALFLIFE_SEC = 30.0              # exponential recency weighting inside the window
MAX_GAP_SEC = 6.0                # longer than this is a discontinuity, not a stall

# Ridge strength, in units of "how many typical observations is the prior
# worth", and the evidence needed to halve it in each channel.
_PRIOR_STRENGTH = 2.5
_PRIOR_FADE_UNITS = 8.0
_PRIOR_FADE_MB = 32.0

# A run with no progress at all for this long is stalled rather than merely
# slow; the lost seconds are added to the estimate instead of being ignored.
_STALL_GRACE_SEC = 8.0

# MB of evidence at which the byte channel's fitted cost is trusted half-and-half
# against its prior (see ``_temper``). Below it the fit is being extrapolated far
# beyond what it measured: `byte_sec = window_time / window_MB` divides by a
# quantity that can be arbitrarily close to zero while hundreds of megabytes are
# still queued behind it.
#
# The **unit** channel gets no such blend, and measurement says it must not:
# conservation already bounds `unit_sec <= window_time / window_units`, so it
# cannot run away the same way, and blending it back toward a generic prior was
# strictly worse on every scenario - a stepwise phase whose prior was 2.8x off
# settled at 112% error with the blend and 37% without, while the opening
# estimate it was supposed to protect was marginally BETTER without it.
_CONF_MB = 20.0

# How much more than the measured transfer cost a megabyte may be charged before
# we stop believing it (see ``_temper``).
_BYTE_COST_SLACK = 2.5

# Totals that grew this recently mean work is still arriving, so counters
# reading "all done" are not to be trusted yet (see ``is_open_ended``).
_OPEN_ENDED_SEC = 6.0

# ...and while that is true, a remainder this small is the two counters being
# momentarily out of step, not a queue. Requiring an exactly-zero remainder made
# the flag - and therefore the whole ETA cell - alternate on every repaint: the
# trailing stretch runs "total grows to 201 / done catches up to 201 / total
# grows to 202", so half the frames read "Finishing…" and half read "00:01",
# about three times a second for the entire half-minute. The screen that was
# lying about being done became a screen that flickered instead.
_OPEN_ENDED_SLACK_UNITS = 2.0

# Display smoothing time constants (seconds), not per-repaint factors.
_SMOOTH_TAU_SEC = 8.0
_SMOOTH_TAU_FAST = 2.5

# Horizon for the Speed read-out. Short on purpose - see ``bytes_per_sec``.
_SPEED_WINDOW_SEC = 10.0

# Remaining work below this is rounding dust, not work: summing chunk sizes in
# floating point leaves a sliver behind, and a sliver kept the clock off 00:00
# after the last byte had landed.
_DONE_UNITS_EPS = 1e-3
_DONE_MB_EPS = 0.05


@dataclass
class _Bin:
    """One time bin of observed work."""
    t_end: float
    dt: float
    units: float
    mb: float


def format_duration(seconds: float | None, *, approximate: bool = False) -> str:
    """Render an ETA the way the metrics row wants it.

    ``None`` (nothing to base an estimate on) renders as "Estimating"; anything
    an hour or over gets an H:MM:SS clock, because ``strftime('%M:%S')`` on a
    90-minute estimate silently prints "30:00" and understates it by an hour.
    ``approximate`` prefixes "~" - the model still leaning on its priors.
    """
    if seconds is None:
        return "Estimating"
    secs = max(0, int(round(seconds)))
    if secs >= 3600:
        hours, rem = divmod(secs, 3600)
        minutes, s = divmod(rem, 60)
        text = f"{hours}:{minutes:02d}:{s:02d}"
    else:
        minutes, s = divmod(secs, 60)
        text = f"{minutes:02d}:{s:02d}"
    return f"~{text}" if approximate else text


def format_elapsed(seconds: float) -> str:
    """MM:SS / H:MM:SS elapsed clock (no approximation marker)."""
    return format_duration(max(0.0, seconds))


class ProgressEstimator:
    """Adaptive time-remaining estimator for one phase of work.

    Feed it cumulative totals via :meth:`update` as often as you like (it is
    idempotent - repeated identical values are free), then read
    :meth:`eta_seconds` / :meth:`eta_text` / :attr:`bytes_per_sec`.

    The two channels are generic on purpose:

    ============  ==========================  =============================
    phase         unit channel                byte channel
    ============  ==========================  =============================
    download      files                       bytes transferred
    sync          files                       bytes transferred
    post-process  files converted             source bytes read
    Panopto DL    recordings                  bytes transferred
    transcription recordings (+ fractional)   - (unused, pass 0)
    analysis      courses                     - (unused, pass 0)
    ============  ==========================  =============================

    A phase that only has one meaningful channel simply leaves the other at
    zero; the fit degenerates gracefully to a single-channel average.
    """

    __slots__ = (
        '_prior_unit_sec', '_prior_byte_sec', '_bucket_sec', '_window_sec',
        '_halflife_sec', '_max_gap_sec', '_bins', '_open_t0', '_open_dt',
        '_open_units', '_open_mb', '_last_units', '_last_mb', '_last_t',
        '_units_total', '_mb_total', '_seen_units', '_seen_mb', '_started_at',
        '_display_eta', '_display_t', '_rate_bps', '_last_progress_t',
        '_max_unit_sec', '_total_grew_at',
    )

    def __init__(self, *, prior_unit_sec: float = DEFAULT_UNIT_SEC,
                 prior_byte_rate: float = DEFAULT_BYTE_RATE,
                 bucket_sec: float = BUCKET_SEC,
                 window_sec: float = WINDOW_SEC,
                 halflife_sec: float = HALFLIFE_SEC,
                 max_gap_sec: float = MAX_GAP_SEC,
                 max_unit_sec: float = MAX_UNIT_SEC) -> None:
        # Per-instance ceiling: transcribing a 45-minute lecture on a CPU is a
        # legitimate half-hour unit, while a download unit costing half an hour
        # means the fit has gone wrong. One shared rail cannot serve both.
        self._max_unit_sec = max(1.0, float(max_unit_sec))
        self._prior_unit_sec = _clamp(prior_unit_sec, MIN_UNIT_SEC, self._max_unit_sec)
        self._prior_byte_sec = MB / _clamp(prior_byte_rate, MIN_BYTE_RATE, MAX_BYTE_RATE)
        self._bucket_sec = max(0.25, float(bucket_sec))
        self._window_sec = max(self._bucket_sec * 3, float(window_sec))
        self._halflife_sec = max(1.0, float(halflife_sec))
        self._max_gap_sec = max(self._bucket_sec, float(max_gap_sec))
        self.reset()

    # ── Lifecycle ───────────────────────────────────────────────────────────

    def reset(self, now: float | None = None) -> None:
        """Drop all observations. Learned priors are kept (see ``export_priors``)."""
        now = _now(now)
        self._bins: deque = deque()
        self._open_t0 = now
        self._open_dt = 0.0
        self._open_units = 0.0
        self._open_mb = 0.0
        self._last_units = 0.0
        self._last_mb = 0.0
        self._last_t = now
        self._units_total = 0.0
        self._mb_total = 0.0
        self._seen_units = 0.0
        self._seen_mb = 0.0
        self._started_at = now
        self._last_progress_t = now
        # None, not a back-dated timestamp: the caller may drive this from a
        # clock with any origin (the tests do), and a sentinel computed from
        # wall time then reads as "grew a moment ago" forever.
        self._total_grew_at = None
        self._display_eta = None
        self._display_t = now
        self._rate_bps = 0.0

    # ── Observation ─────────────────────────────────────────────────────────

    def update(self, *, units_done: float = 0.0, bytes_done: float = 0.0,
               units_total: float = 0.0, bytes_total: float = 0.0,
               now: float | None = None) -> None:
        """Record cumulative progress.

        All four arguments are *cumulative totals*, not deltas, so a caller can
        hand over whatever its counters currently say without tracking what it
        reported last time. Totals may grow mid-run (Canvas discovers secondary
        attachments as it goes) - that is expected and handled.
        """
        now = _now(now)
        units_done = max(0.0, float(units_done or 0.0))
        mb_done = max(0.0, float(bytes_done or 0.0)) / MB

        # Totals never shrink below what is already done: a phase with unknown
        # size (Panopto, where byte totals are not known until each stream is
        # resolved) reports total == done, which correctly contributes zero
        # remaining bytes and lets the unit channel carry the estimate.
        # Work arriving AFTER the counters already read "all done" is the only
        # growth that matters here (see ``is_open_ended``). Learning the total
        # for the first time is not growth, and neither is a mid-run discovery
        # while there is still a queue - both are ordinary and neither means the
        # screen is lying about being finished.
        new_units_total = max(float(units_total or 0.0), units_done)
        was_done = (self._units_total > 0
                    and (self._units_total - self._last_units) <= _DONE_UNITS_EPS)
        if was_done and new_units_total > self._units_total:
            self._total_grew_at = now
        self._units_total = new_units_total
        self._mb_total = max(max(0.0, float(bytes_total or 0.0)) / MB, mb_done)

        dt = now - self._last_t
        d_units = units_done - self._last_units
        d_mb = mb_done - self._last_mb
        self._last_t = now
        self._last_units = units_done
        self._last_mb = mb_done

        if dt < 0:
            # Clock went backwards (NTP step). Resync without inventing work.
            self._open_t0 = now
            return

        if dt > self._max_gap_sec:
            # Discontinuity, not a stall: a Streamlit rerun between courses, the
            # post-processing phase, a modal. The work that completed inside the
            # gap is real but its duration was never observed, so counting it
            # would report a fictional burst of speed. Drop the delta, close the
            # open bin, and restart the clock here.
            self._close_open_bin(now)
            self._last_progress_t = now
            return

        # Counters can legitimately go backwards (a failed download attempt
        # rolls its partial bytes back so the MB dashboard never double-counts).
        d_units = max(0.0, d_units)
        d_mb = max(0.0, d_mb)
        if d_units > 0 or d_mb > 0:
            self._last_progress_t = now

        self._seen_units += d_units
        self._seen_mb += d_mb
        self._open_dt += dt
        self._open_units += d_units
        self._open_mb += d_mb

        if now - self._open_t0 >= self._bucket_sec:
            self._close_open_bin(now)

        self._evict(now)

    def _close_open_bin(self, now: float | None = None) -> None:
        now = _now(now)
        if self._open_dt > 0 or self._open_units > 0 or self._open_mb > 0:
            self._bins.append(_Bin(now, self._open_dt, self._open_units, self._open_mb))
        self._open_t0 = now
        self._open_dt = 0.0
        self._open_units = 0.0
        self._open_mb = 0.0

    def _evict(self, now: float) -> None:
        cutoff = now - self._window_sec
        while self._bins and self._bins[0].t_end < cutoff:
            self._bins.popleft()

    # ── Fit ─────────────────────────────────────────────────────────────────

    def _solve(self, now: float) -> tuple[float, float, bool]:
        """Return ``(unit_sec, byte_sec_per_mb, has_evidence)`` over the window.

        ``has_evidence`` is False when the window holds no observed work at
        all - the caller needs to know that the numbers are pure prior.

        The fit is a weighted least-squares split of the window's elapsed time
        across the two channels, **subject to conserving that elapsed time**:

            unit_sec · units_in_window + byte_sec · mb_in_window = time_in_window

        The constraint is what makes the estimate trustworthy, and dropping it
        was the single biggest error in the first version of this model. Once a
        run settles into a steady rhythm, every bin advances both channels
        together and the two are almost perfectly collinear: "2.3 s per file"
        and "0.38 s per MB" explain the observed data equally well, so an
        unconstrained fit lands wherever its regulariser happens to pull it and
        the resulting ETA was out by 2x with a textbook-clean residual.
        Conservation removes that freedom - whatever split it picks, replaying
        the *observed* mix of work reproduces the *observed* clock, so as long
        as the work still queued resembles the work just done, the projection
        is right. The least-squares part is then only deciding how to attribute
        cost between the channels, which is exactly what matters when the
        remaining mix is NOT like the observed one (a run that opens with
        zero-byte shortcuts and then hits 800 MB of PDFs).

        Conservation also subsumes stall handling for free: dead time inside
        the window - rate-limit backoff, a slow API - is time the constraint
        insists on allocating, so it lands in the coefficients instead of
        vanishing. (True *discontinuities* are excluded upstream by the
        ``_max_gap_sec`` guard, so a Streamlit rerun between courses is never
        mistaken for a stall.)
        """
        rows: list[tuple[float, float, float, float]] = []  # (w, dt, du, dmb)
        for b in self._bins:
            w = 0.5 ** (max(0.0, now - b.t_end) / self._halflife_sec)
            rows.append((w, b.dt, b.units, b.mb))
        # The open bin counts even when no time has accrued in it yet. Callers
        # advance their counter and repaint in the same instant, so a completion
        # that lands on a bin boundary opens the next bin with work but dt=0 -
        # dropping it hid every such completion from the fit until the next
        # tick, and in a phase whose cadence lines up with the bin width that
        # meant *every* completion, doubling the fitted per-unit cost.
        if self._open_dt > 0 or self._open_units > 0 or self._open_mb > 0:
            rows.append((1.0, self._open_dt, self._open_units, self._open_mb))

        # Dead time at either END of the window is unattributable and must not
        # enter the conservation sum; interior gaps stay in, because a
        # rate-limit sleep *between* two completions genuinely is part of what a
        # unit costs. The two ends fail in opposite directions and both were
        # measured:
        #
        # * **Trailing** dead time is the *unfinished* unit. Leaving it in makes
        #   the fitted per-unit cost sawtooth - correct the instant a unit
        #   lands, then climbing until the next one - so a phase of 9 s units
        #   fitted anywhere between 9 s and 18 s depending on when you looked.
        # * **Leading** dead time is the phase's one-off setup: 45 s of Canvas
        #   metadata latency before the first file lands. Charging it to the
        #   handful of files that arrive next, then extrapolating across the
        #   whole course, is what made the opening estimate read 13 minutes on a
        #   4-minute remainder (and hours before the other brakes went in). It
        #   happens once; it is not what the next file will cost.
        while rows and rows[-1][2] <= 0 and rows[-1][3] <= 0:
            rows.pop()

        # The leading run is trimmed rather than dropped, because some of it is
        # genuinely the first unit's own duration. How much? Exactly as much
        # lead-in as a typical unit gets in the rest of this window - which the
        # window itself can answer, so nothing has to be guessed. A count-only
        # phase whose units take 9 s keeps its 9 s of lead-in (dropping it
        # halved the fitted cost and cost 15 points of accuracy); a download
        # that idled 45 s on metadata before its first 2 s file keeps 2 s.
        lead = 0
        while lead < len(rows) and rows[lead][2] <= 0 and rows[lead][3] <= 0:
            lead += 1
        if lead:
            body_dt = sum(r[1] for r in rows[lead:])
            body_work = sum(1 for r in rows[lead:] if r[2] > 0 or r[3] > 0)
            budget = (body_dt / body_work) if body_work else 0.0
            keep, acc = lead, 0.0
            while keep > 0 and acc + rows[keep - 1][1] <= budget:
                keep -= 1
                acc += rows[keep][1]
            rows = rows[keep:]

        w_t = w_u = w_b = 0.0
        s_uu = s_ub = s_bb = 0.0
        for w, dt, du, dmb in rows:
            w_t += w * dt
            w_u += w * du
            w_b += w * dmb
            s_uu += w * du * du
            s_ub += w * du * dmb
            s_bb += w * dmb * dmb

        a0, b0 = self._prior_unit_sec, self._prior_byte_sec

        # No measurable work at all: nothing to fit, so the priors stand.
        if w_t <= 0 or (w_u <= 0 and w_b <= 0):
            return a0, b0, False
        # Single-channel window - the constraint alone determines that channel,
        # and the other keeps its prior until it has evidence of its own. This
        # is the shortcut-only opening stretch, and it is why the dashboard can
        # show a number there at all.
        if w_b <= 0:
            return self._temper(w_t / w_u, b0, w_b) + (True,)
        if w_u <= 0:
            return self._temper(a0, w_t / w_b, w_b) + (True,)

        # Both channels active. Eliminate byte_sec via the constraint
        # (byte_sec = (w_t - unit_sec·w_u) / w_b) and minimise the residual over
        # the single remaining degree of freedom, ridge-pulled toward the priors.
        #
        # Substituting turns each row's residual into  y - unit_sec·x  with
        #     x = du - dmb·(w_u / w_b)      y = dt - dmb·(w_t / w_b)
        k_u = w_u / w_b
        k_t = w_t / w_b
        num = den = 0.0
        for w, dt, du, dmb in rows:
            x = du - dmb * k_u
            y = dt - dmb * k_t
            num += w * x * y
            den += w * x * x

        # Ridge terms. Their strength is scaled to the size of a typical
        # observation in each channel, so the prior is worth a couple of bins'
        # worth of evidence regardless of whether a bin carries 1 file or 40 MB
        # - a fixed constant would silently dominate one channel and be noise in
        # the other. It then fades as that channel accrues real evidence.
        n_rows = float(len(rows)) or 1.0
        scale_u = max(s_uu / n_rows, 1e-6)
        scale_b = max(s_bb / n_rows, 1e-6)
        lam_u = _PRIOR_STRENGTH * scale_u / (1.0 + self._seen_units / _PRIOR_FADE_UNITS)
        lam_b = _PRIOR_STRENGTH * scale_b / (1.0 + self._seen_mb / _PRIOR_FADE_MB)
        # byte_sec's prior expressed as a pull on unit_sec through the constraint.
        num += lam_u * a0 + lam_b * k_u * (k_t - b0)
        den += lam_u + lam_b * k_u * k_u

        unit_sec = num / den if den > 1e-12 else a0
        if not _finite(unit_sec):
            unit_sec = a0

        # Non-negativity: work cannot buy back time. Pinning a channel to zero
        # hands its whole share to the other one via the same constraint.
        unit_sec = max(0.0, min(unit_sec, w_t / w_u))
        byte_sec = (w_t - unit_sec * w_u) / w_b
        return self._temper(unit_sec, byte_sec, w_b) + (True,)

    def _temper(self, unit_sec: float, byte_sec: float,
                w_b: float) -> tuple[float, float]:
        """Hold a coefficient back from being extrapolated further than it earned.

        Conservation makes the fit explain the window it saw. It says nothing
        about whether that window is a fair sample of the work still queued, and
        early in a run it is not: a phase opens with tens of seconds of Canvas
        metadata latency, a couple of files land, and the constraint dutifully
        charges all of it to whichever channel moved. Multiply that by the
        hundreds of files and hundreds of megabytes still ahead and the first
        estimate of a real download read **5:37:34** on a run that finished in
        minutes. The fit was not wrong about the window - it was asked to
        extrapolate a setup cost across the entire run.

        Two brakes, both scaled to how much the channel actually observed:

        * **Confidence blending.** A cost fitted on half a megabyte and then
          applied to 800 MB is amplified noise, not a measurement, so it is
          blended back toward the prior in proportion to the evidence behind it.
        * **A throughput anchor on the byte channel.** The recent transfer rate
          is the one thing we measure directly, and it is on screen next to the
          estimate. Per-MB cost above what the connection is currently
          delivering is real - queueing, hashing, disk - but a *multiple* of it
          is setup latency that will not repeat per megabyte. Capping there also
          stops the two cells contradicting each other, which is what the user
          sees first: "3.3 MB/s, 828 MB left, why does it say five hours?"
        """
        conf_b = w_b / (w_b + _CONF_MB) if (w_b + _CONF_MB) > 0 else 1.0
        byte_sec = conf_b * byte_sec + (1.0 - conf_b) * self._prior_byte_sec

        rate = self.bytes_per_sec
        if rate > 0:
            byte_sec = min(byte_sec, _BYTE_COST_SLACK * MB / rate)

        return (_clamp(unit_sec, MIN_UNIT_SEC, self._max_unit_sec),
                _clamp(byte_sec, MB / MAX_BYTE_RATE, MB / MIN_BYTE_RATE))

    # ── Read-out ────────────────────────────────────────────────────────────

    def remaining(self) -> tuple[float, float]:
        """``(units_remaining, mb_remaining)`` - both floored at zero."""
        return (max(0.0, self._units_total - self._last_units),
                max(0.0, self._mb_total - self._last_mb))

    @property
    def bytes_per_sec(self) -> float:
        """Transfer rate over the recent window, not since run start.

        The cumulative average the dashboard used to print is diluted by every
        pause and by the whole zero-byte opening phase - it read 0.7 MB/s on a
        run that was actually moving several times faster. This reads over a
        short horizon of its own (deliberately much shorter than the ETA's
        window: the ETA wants stability, a speedometer wants to be current), so
        it tracks what is happening now and a frozen transfer decays to zero
        rather than coasting on history.
        """
        cutoff = self._last_t - _SPEED_WINDOW_SEC
        mb = dt = 0.0
        for b in self._bins:
            if b.t_end < cutoff:
                continue
            mb += b.mb
            dt += b.dt
        mb += self._open_mb
        dt += self._open_dt
        if dt <= 0:
            return 0.0
        self._rate_bps = (mb / dt) * MB
        return self._rate_bps

    @property
    def mb_per_sec(self) -> float:
        """Convenience wrapper - the metrics row prints MB/s."""
        return self.bytes_per_sec / MB

    @property
    def elapsed(self) -> float:
        return max(0.0, self._last_t - self._started_at)

    @property
    def is_provisional(self) -> bool:
        """True while the estimate still leans materially on its priors."""
        return not (self._seen_units >= 3.0 or self._seen_mb >= 4.0)

    @property
    def is_open_ended(self) -> bool:
        """True when the counters read "finished" but work is still arriving.

        Canvas produces Pages, ExternalUrl shortcuts and secondary content as it
        goes, and each one raises the numerator AND the denominator in the same
        breath - so the run sits at 100%, total-of-total megabytes and 00:00
        while it is genuinely still working. The last stretch of a real download
        was 30-50 shortcut files over about half a minute with every metric
        already claiming to be done.

        There is no honest countdown available here: nothing knows how many more
        are coming. What the dashboard can do is stop claiming otherwise, which
        is what this flag is for - a held-back bar and "Finishing…" instead of a
        finished-looking screen that is lying.
        """
        if self._total_grew_at is None:
            return False
        units_rem, mb_rem = self.remaining()
        # Bytes keep a tight guard: synthetic items are zero-byte, so a real
        # megabyte remainder means there is genuinely something to count down.
        # Units get slack, because the counters advance from different code
        # paths and land a tick apart (see ``_OPEN_ENDED_SLACK_UNITS``). The
        # ``was_done`` gate upstream is what keeps this narrow - a mid-run
        # discovery while a queue still exists never sets the timestamp at all.
        if units_rem > _OPEN_ENDED_SLACK_UNITS or mb_rem > _DONE_MB_EPS:
            return False
        return 0.0 <= (self._last_t - self._total_grew_at) < _OPEN_ENDED_SEC

    def eta_seconds(self, now: float | None = None) -> float | None:
        """Smoothed seconds remaining, or ``None`` when nothing is estimable.

        ``None`` means the caller has not told us how much work there is
        (both totals zero) - the only case where "Estimating" is the honest
        answer. Everything else produces a number, provisional or not.
        """
        now = _now(now)
        units_rem, mb_rem = self.remaining()

        if self._units_total <= 0 and self._mb_total <= 0:
            self._display_eta = None
            self._display_t = now
            return None
        if units_rem <= _DONE_UNITS_EPS and mb_rem <= _DONE_MB_EPS:
            self._display_eta = 0.0
            self._display_t = now
            return 0.0

        # One smoothing step per repaint. A screen that reads both eta_seconds()
        # and eta_text() would otherwise blend the correction in twice and
        # converge at roughly double the intended rate.
        if self._display_eta is not None and (now - self._display_t) < 0.05:
            return self._display_eta

        unit_sec, byte_sec, has_evidence = self._solve(now)
        raw = unit_sec * units_rem + byte_sec * mb_rem

        # The unit currently in flight is partly paid for: it has been running
        # since the last completion, and the fit (which now excludes that
        # trailing stretch) prices it as if it had not started. Credit the time
        # already spent, capped at one whole unit so a hang cannot credit its
        # way to zero. Byte-moving phases post progress every chunk, so this is
        # ~0 there and only bites where it should - the stepwise phases.
        in_flight = max(0.0, now - self._last_progress_t)
        raw -= min(in_flight, unit_sec)

        # A freeze *inside* the window is already priced in - conservation
        # insists the dead seconds be attributed to the coefficients. But a
        # freeze longer than the window leaves no live rows at all, the fit
        # falls back to its priors, and the clock would count confidently down
        # toward a finish that is not coming. Charge those seconds explicitly,
        # and only in that case, or the two mechanisms double-count.
        if not has_evidence:
            raw += max(0.0, in_flight - _STALL_GRACE_SEC)

        raw = _clamp(raw, 0.0, 30 * 24 * 3600.0)
        return self._smooth(raw, now)

    def _smooth(self, raw: float, now: float) -> float:
        """Damp the displayed value so it counts down instead of flickering.

        The baseline is not the previous *estimate* but the previous estimate
        minus the time that has since passed - i.e. a clock that is already
        ticking. On a correct trajectory that baseline is already right, so the
        blend contributes nothing and there is no lag; it only does work when
        the model has actually changed its mind.

        The blend rate is a **time constant, not a per-call factor**. A fixed
        per-call alpha ties the convergence speed to the repaint rate, which is
        not a property of the download: the same run smoothed 8x faster on a
        chatty screen than on a quiet one, and a phase that repaints only every
        few seconds would lag its true estimate by 30% indefinitely.
        """
        prev = self._display_eta
        dt = max(0.0, now - self._display_t)
        self._display_t = now

        if prev is None:
            self._display_eta = raw
            return raw

        expected = max(0.0, prev - dt)
        delta = raw - expected
        # A regime change (a new phase, a stall clearing, the network halving)
        # converges faster: holding on to a stale number would be worse than a
        # visible jump. Everything else eases in over ~8 s.
        tau = _SMOOTH_TAU_FAST if abs(delta) > max(15.0, 0.6 * expected) else _SMOOTH_TAU_SEC
        alpha = 1.0 - math.exp(-dt / tau) if dt > 0 else 0.0
        value = max(0.0, expected + alpha * delta)
        self._display_eta = value
        return value

    def eta_text(self, now: float | None = None) -> str:
        """The string the metrics row renders."""
        if self.is_open_ended:
            return "Finishing…"
        secs = self.eta_seconds(now)
        if secs is None:
            return "Estimating"
        if secs < 1.0:
            units_rem, mb_rem = self.remaining()
            if units_rem > _DONE_UNITS_EPS or mb_rem > _DONE_MB_EPS:
                secs = 1.0  # never claim "00:00" while work is still queued
        return format_duration(secs, approximate=self.is_provisional)

    # ── Cross-run calibration ───────────────────────────────────────────────

    def export_priors(self) -> dict:
        """Learned costs, for seeding the next phase/run in the same session.

        Only exported once there is real evidence - otherwise a phase would
        "learn" its own defaults and pass them on as if they were measured.
        """
        if self.is_provisional:
            return {}
        unit_sec, byte_sec, _ok = self._solve(self._last_t)
        out: dict = {}
        if self._seen_units >= 3.0:
            out['prior_unit_sec'] = unit_sec
        if self._seen_mb >= 4.0 and byte_sec > 0:
            out['prior_byte_rate'] = MB / byte_sec
        return out


# ── Phase presets ───────────────────────────────────────────────────────────
# Every screen builds its estimator through one of these, so the tuning lives
# here instead of being re-derived (differently) at each call site.

def transfer_estimator(**priors) -> ProgressEstimator:
    """For byte-moving phases: Canvas downloads, syncs, Panopto media.

    Work arrives many times a second, so the default short window tracks a
    changing connection quickly. ``priors`` accepts ``prior_unit_sec`` /
    ``prior_byte_rate`` carried over from an earlier phase or run.
    """
    # Downloading one file has fixed overhead measured in seconds, never in
    # minutes. The module-wide ceiling has to accommodate Office conversions and
    # transcription, and leaving a transfer phase on that rail let a bad early
    # window project half a minute per file across a whole course.
    priors.setdefault('max_unit_sec', 20.0)
    return ProgressEstimator(**priors)


def stepwise_estimator(prior_unit_sec: float, **priors) -> ProgressEstimator:
    """For phases whose progress arrives in slow, chunky steps.

    Course analysis (~seconds per course), Office conversions (~seconds per
    file) and transcription (~minutes per recording) all complete one unit at a
    time with long silences in between. The transfer defaults mis-read that
    rhythm: a 30 s half-life up-weights the elapsed time of the current, still
    unfinished unit against the completions that came before it, which biases
    the per-unit cost high. A window and half-life measured in minutes, and a
    realistic per-unit prior, are what these phases need.
    """
    priors.setdefault('window_sec', 420.0)
    priors.setdefault('halflife_sec', 180.0)
    priors.setdefault('bucket_sec', 3.0)
    # These phases legitimately sit silent for a long time inside one unit
    # (a 12-minute transcription), which must not read as a rerun boundary.
    priors.setdefault('max_gap_sec', 45.0)
    # A unit that legitimately costs minutes needs headroom above the transfer
    # default's 3-minute rail, or the rail itself becomes the estimate.
    priors.setdefault('max_unit_sec', max(MAX_UNIT_SEC, prior_unit_sec * 20.0))
    return ProgressEstimator(prior_unit_sec=prior_unit_sec, **priors)


# Transcription is the one phase whose per-unit cost spans two orders of
# magnitude for reasons the app cannot see in advance: a 45-minute lecture is
# ~2 minutes on a GPU with the small model and well over half an hour on a CPU
# with a large one. Four minutes is the middle of that range, marked provisional
# until the first recording finishes and replaces it with a measurement.
PANOPTO_TRANSCRIBE_PRIOR_SEC = 240.0
# Media download: a recording is one HTTP stream remuxed by ffmpeg, so its fixed
# overhead is the delivery-node resolve plus process spawn.
PANOPTO_DOWNLOAD_PRIOR_SEC = 4.0


def panopto_estimators(transfer_priors: dict | None = None) -> dict:
    """The two estimable Panopto phases, keyed by phase name.

    Only the *byte rate* is inherited from ``transfer_priors``: that describes
    the connection and carries over fine. The per-unit cost does not - a
    Panopto recording's overhead is a delivery-node resolve plus an ffmpeg
    spawn, which has nothing to do with what a Canvas file costs.

    Discovery is deliberately absent: the folder walk finds out how many folders
    exist by walking them, so there is no denominator to estimate against and
    that screen shows elapsed time instead of inventing a countdown.
    """
    byte_rate = (transfer_priors or {}).get('prior_byte_rate')
    return {
        'download': ProgressEstimator(
            prior_unit_sec=PANOPTO_DOWNLOAD_PRIOR_SEC,
            **({'prior_byte_rate': byte_rate} if byte_rate else {})),
        'transcribe': stepwise_estimator(PANOPTO_TRANSCRIBE_PRIOR_SEC),
    }


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value)


def _clamp(value: float, low: float, high: float) -> float:
    if not _finite(value):
        return low
    return max(low, min(high, float(value)))


def _now(now: float | None) -> float:
    return _time.time() if now is None else float(now)
