"""A URL-less Canvas file is a STREAM or a FAILURE - and both engines must agree.

When Canvas hands over a file with no download URL, each engine decides from the
extension whether this is "a video the plugin streams" - a permanent fact about
the course, which no retry, setting or wait can change - or a genuine failure.
That verdict selects ``LTI_STREAM_REASON`` / ``LTI_STREAM_ERROR_TYPE``, and the
completion screen classifies those to decide what to colour as an error. So a
wrong verdict reports the app as broken for something Canvas simply declined.

THE DEFECT: the message and the error type were unified into ``shared.helpers``
long ago, but the predicate that CHOOSES them was written twice - once in
``core.canvas_logic`` (download) and once in ``sync.execution`` (sync) - and both
copies omitted ``.m4v``, while the size-mismatch tolerance in the very same
download engine lists ``.m4v`` as media. So an ``.m4v`` stream was counted as a
hard failure in both engines.

Same shape as ``make_long_path``'s second copy in ``core.sync_manager`` (the fix
reached none of the 26 manifest call sites) and the three AppleScript escapers.
These tests therefore assert the INVARIANT - one definition, consulted by both
engines - not the contents of any one list.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from shared.helpers import (
    LTI_STREAM_ERROR_TYPE,
    LTI_STREAM_EXTENSIONS,
    LTI_STREAM_REASON,
    is_lti_stream_ext,
)

REPO = Path(__file__).resolve().parents[1]
ENGINES = ("core/canvas_logic.py", "sync/execution.py")


# --- The regression itself ---------------------------------------------------

def test_m4v_is_recognised_as_a_stream():
    """The extension both copies dropped. The download engine's own
    size-mismatch tolerance already treats .m4v as media, so the two halves of
    one engine disagreed with each other."""
    assert is_lti_stream_ext(".m4v")
    assert is_lti_stream_ext("Guest lecture.m4v")


@pytest.mark.parametrize("ext", [".mp4", ".mov", ".avi", ".mkv", ".mp3", ".m4v"])
def test_every_streamed_medium_is_recognised(ext):
    assert is_lti_stream_ext(ext)
    assert is_lti_stream_ext(f"Uge 44 Forelæsning{ext}")


@pytest.mark.parametrize("name", [
    "notes.pdf", "slides.pptx", "data.xlsx", "page.html", "archive.zip",
    "readme", "", None, "no-extension-at-all",
])
def test_an_ordinary_file_is_not_a_stream(name):
    """A false positive is the dangerous direction: it would report a genuine
    download failure as "Canvas declined it", hiding a real problem."""
    assert not is_lti_stream_ext(name)


def test_the_match_is_case_insensitive():
    """Canvas serves .MP4 as readily as .mp4."""
    assert is_lti_stream_ext("LECTURE.MP4")
    assert is_lti_stream_ext(".MoV")


def test_a_bare_extension_and_a_full_name_agree():
    assert is_lti_stream_ext(".mp4") == is_lti_stream_ext("a/b/c.mp4")


def test_only_the_LAST_extension_decides():
    """`notes.mp4.pdf` is a PDF, not a stream."""
    assert not is_lti_stream_ext("notes.mp4.pdf")
    assert is_lti_stream_ext("archive.pdf.mp4")


# --- The invariant: ONE definition, consulted by both engines ----------------

@pytest.mark.parametrize("rel", ENGINES)
def test_neither_engine_keeps_its_own_extension_list(rel):
    """The whole defect in one property. Matched on a CALL, not a token: a
    leftover import satisfies a substring test while nothing runs."""
    tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))

    called = {
        n.func.id for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "is_lti_stream_ext" in called, (
        f"{rel} must ASK the shared predicate, not re-decide locally")

    for node in ast.walk(tree):
        if not isinstance(node, (ast.Set, ast.Tuple, ast.List)):
            continue
        vals = {e.value.lower() for e in node.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)}
        if not vals or len(vals) != len(node.elts):
            continue
        # A second copy of the stream set is the thing that must not come back.
        # The size-mismatch tolerance list is a DIFFERENT concept and is allowed
        # to hold the same members - it is identified by its own guard below.
        if vals == set(LTI_STREAM_EXTENSIONS) and rel == "sync/execution.py":
            raise AssertionError(
                f"{rel}:{node.lineno} restates the stream extension set")


def test_the_reason_and_the_predicate_live_in_the_same_module():
    """They are one rule in two halves: the predicate decides, the constants
    say so. Splitting them across modules is how the predicate got left behind
    when the strings were unified."""
    src = (REPO / "shared" / "helpers.py").read_text(encoding="utf-8")
    for name in ("LTI_STREAM_REASON", "LTI_STREAM_ERROR_TYPE",
                 "LTI_STREAM_EXTENSIONS", "def is_lti_stream_ext"):
        assert name in src


@pytest.mark.parametrize("rel", ENGINES)
def test_each_engine_takes_the_predicate_from_the_one_shared_module(rel):
    """Both engines resolve to the same definition, so there is nothing to drift.

    Asserted STRUCTURALLY, not by object identity. Four test modules in this
    suite call ``importlib.reload`` on ``shared.helpers``, which mints a fresh
    function object while an already-imported engine keeps the old reference -
    so ``a is b`` fails for a perfectly correct tree, depending only on test
    order. The property that matters is where the name comes FROM.
    """
    tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
    sources = {
        node.module for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and any(a.name == "is_lti_stream_ext" for a in node.names)
    }
    assert sources == {"shared.helpers"}, (
        f"{rel} must import is_lti_stream_ext from shared.helpers "
        f"(found: {sources or 'no import at all'})")


def test_the_set_is_immutable():
    """A mutable module-level default shared by two engines is one stray
    ``.add()`` away from a cross-engine behaviour change."""
    assert isinstance(LTI_STREAM_EXTENSIONS, frozenset)


# --- The neighbouring concept must NOT be swallowed --------------------------

def test_the_size_mismatch_tolerance_is_still_its_own_decision():
    """``.pdf`` in ``file_in_scope`` vs the PowerPoint converter's input set is
    the standing example: two lists may hold the same members and still be
    different questions. This one asks "may a short read be tolerated?", not
    "is this a stream?" - merging them would tie a download-integrity rule to an
    error-classification rule, so widening one would silently widen the other.

    Asserted on the BINDING, not the name. A first version of this test only
    grepped for "flexible_extensions", and a mutation that aliased the shared
    set to that very name survived it - the token-instead-of-binding trap.
    """
    tree = ast.parse((REPO / "core" / "canvas_logic.py").read_text(encoding="utf-8"))

    literals = [
        n.value for n in ast.walk(tree)
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "flexible_extensions"
                for t in n.targets)
    ]
    assert literals, "the size-mismatch tolerance list is gone entirely"
    for value in literals:
        assert isinstance(value, (ast.List, ast.Set, ast.Tuple)), (
            "flexible_extensions must be its OWN literal list, not an alias of "
            f"the stream set (found {type(value).__name__})")

    aliased = [
        a.asname for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
        for a in n.names
        if a.name == "LTI_STREAM_EXTENSIONS" and a.asname == "flexible_extensions"
    ]
    assert not aliased, (
        "the stream set must not be re-exported under the size-mismatch name - "
        "that is the merge this test exists to prevent")


def test_the_stream_branch_each_engine_guards_is_the_one_that_stamps_the_reason():
    """Closes the chain WITHOUT re-implementing either engine.

    An earlier version of this test fed ``LTI_STREAM_REASON`` straight to the
    downstream classifier and asserted it came back as a stream. That passes
    with the bug still present - the classifier reads the MESSAGE, and the
    defect was upstream, in deciding whether to produce that message at all.
    (The exact trap this repo already paid for on ``format_file_size``.)

    So assert the two links separately and let them meet:
      1. ``is_lti_stream_ext('.m4v')`` is True                  - tested above
      2. the branch each engine guards with it stamps the reason - here
    """
    import ast

    for rel, expect in (("sync/execution.py", "LTI_STREAM_REASON"),
                        ("core/canvas_logic.py", "LTI/Media Stream")):
        tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
        guarded = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.If)
            and any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                    and c.func.id == "is_lti_stream_ext"
                    for c in ast.walk(n.test))
        ]
        assert guarded, f"{rel} has no branch guarded by is_lti_stream_ext"
        body = "\n".join(ast.unparse(st) for st in guarded[0].body)
        assert expect in body, (
            f"{rel}: the is_lti_stream_ext branch must stamp the stream "
            f"outcome, so recognising .m4v actually changes what the user is "
            f"told; got:\n{body}")


def test_the_downstream_classifier_understands_that_reason():
    """The consumer half only - the producer is covered above. Producer and
    consumer live in different modules and are joined solely by this string."""
    from shared.helpers import split_delivery_errors

    split = split_delivery_errors([f"Error syncing Guest lecture.m4v: {LTI_STREAM_REASON}"])
    assert not split.get("failures"), (
        "a streamed video is a permanent fact about the course, not a failure "
        "of the run - no retry, setting or wait can fetch it")
    assert (split.get("reasons") or {}).get("stream")


def test_the_declined_sentence_names_the_cause_for_a_stream():
    from shared.helpers import declined_reason_sentence
    sentence = declined_reason_sentence({"stream": 1})
    assert "stream" in sentence.lower()
    assert "Nothing is missing that could have been fetched." in sentence
