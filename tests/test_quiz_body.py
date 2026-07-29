"""A quiz's saved file must never claim the quiz is empty.

Canvas exposes an online quiz TWICE - as a quiz, and as its shadow assignment -
and a module can hold either. Reached through the assignment, ``description`` is
empty by nature, because for a quiz the content IS the questions. The app saved
that empty string, and ``_save_secondary_entity`` rendered its generic
placeholder, so the file read **"(No content provided)"** - a statement about a
quiz that has questions Canvas simply will not serve to a student.

Measured on course 43660, both files present for quiz "læring og innovation"::

    Assignments/Quiz læring og innovation.md  assignments/32347  (No content provided)
    Quizzes/Quiz læring og innovation.md      quizzes/107362     Could not load quiz questions.

Two defects, one root: questions were fetched in exactly ONE of the five places
a quiz can be saved, and that one caught the wrong exception.

**``Forbidden`` is a SIBLING of ``Unauthorized`` under ``CanvasException``, not
a subclass.** So ``except (Unauthorized, ResourceDoesNotExist)`` - whose message
("Quiz questions are not accessible...") was written for precisely this case -
never ran, and every student fell through to the generic handler. Verified
against the live API: ``quiz.get_questions()`` raises ``Forbidden`` carrying
``{"status":"unauthorized"}``. The payload says unauthorized; the class does not.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from canvasapi.exceptions import (CanvasException, Forbidden,
                                  ResourceDoesNotExist, Unauthorized)

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core.canvas_logic import (assignment_body_html, quiz_body_html,   # noqa: E402
                               quiz_id_of_assignment)


class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _lazy(raises, items):
    """A stand-in for canvasapi's PaginatedList, which is LAZY.

    ``get_questions()`` touches the network on the first ``next()``, not on the
    call. A double that raises EAGERLY cannot tell a correct implementation
    from one that guards only the call - and that is exactly the bug the first
    refactor here shipped: 21 green tests, and the live API raised straight
    through ``assignment_body_html`` into the caller. Every fixture below
    raises on ITERATION for that reason.
    """
    def gen():
        if raises:
            raise raises
        yield from items
    return gen()


class _Q:
    def __init__(self, raises=None, questions=()):
        self._raises, self._questions = raises, questions
        self.id = 107362
        self.description = ""
        self.title = "Quiz: læring og innovation"

    def get_questions(self):
        return _lazy(self._raises, self._questions)


class _Course:
    def __init__(self, quiz=None, raises=None):
        self._quiz, self._raises = quiz, raises

    def get_quiz(self, qid):
        if self._raises:
            raise self._raises
        return self._quiz


def _forbidden():
    return Forbidden('{"status":"unauthorized","errors":[{"message":"user not '
                     'authorised to perform that action"}]}')


# --------------------------------------------------------------------------
# the exception the real API actually raises
# --------------------------------------------------------------------------

def test_forbidden_is_not_a_subclass_of_unauthorized():
    """The whole reason the informative handler was dead code."""
    assert not issubclass(Forbidden, Unauthorized)
    assert issubclass(Forbidden, CanvasException)


def test_a_student_gets_the_explanation_not_the_generic_message():
    body = quiz_body_html(_Q(raises=_forbidden()))
    assert "does not mean the quiz is empty" in body
    assert "could not be loaded" not in body


@pytest.mark.parametrize("exc", [_forbidden(), Unauthorized("x"),
                                 ResourceDoesNotExist("x")])
def test_every_denial_is_explained_the_same_way(exc):
    assert "does not mean the quiz is empty" in quiz_body_html(_Q(raises=exc))


def test_an_unexpected_failure_still_says_something_true():
    body = quiz_body_html(_Q(raises=RuntimeError("socket reset")))
    assert "could not be loaded" in body
    assert "does not mean the quiz is empty" not in body


def test_a_denial_never_yields_an_empty_body():
    """An empty body is what produced "(No content provided)"."""
    assert quiz_body_html(_Q(raises=_forbidden())).strip() != ""


# --------------------------------------------------------------------------
# the questions themselves
# --------------------------------------------------------------------------

def test_questions_are_rendered_with_their_answers():
    q = _Obj(question_name="Hvad er en organisation?", question_text="<p>?</p>",
             question_type="multiple_choice_question",
             answers=[{"text": "A"}, {"html": "<b>B</b>"}])
    body = quiz_body_html(_Q(questions=[q]))
    assert "Hvad er en organisation?" in body
    assert "multiple_choice_question" in body
    assert "<li>A</li>" in body and "<li><b>B</b></li>" in body


def test_a_question_name_is_escaped():
    q = _Obj(question_name="<script>alert(1)</script>", question_text="",
             question_type="essay_question", answers=None)
    assert "<script>" not in quiz_body_html(_Q(questions=[q]))


def test_the_description_is_kept_above_the_questions():
    quiz = _Q(questions=[])
    quiz.description = "<p>Read chapter 4 first.</p>"
    body = quiz_body_html(quiz)
    assert body.startswith("<p>Read chapter 4 first.</p>")


# --------------------------------------------------------------------------
# an assignment that IS a quiz
# --------------------------------------------------------------------------

REAL = _Obj(id=32347, name="Quiz: læring og innovation", description="",
            submission_types=["online_quiz"], is_quiz_assignment=True,
            quiz_id=107362)


def test_the_real_assignment_is_recognised_as_a_quiz():
    """Field values read from the live API for assignment 32347."""
    assert quiz_id_of_assignment(REAL) == 107362


def test_an_ordinary_assignment_is_not():
    a = _Obj(description="<p>Hand in a report.</p>",
             submission_types=["online_upload"], is_quiz_assignment=False)
    assert quiz_id_of_assignment(a) is None


def test_a_quiz_flagged_only_by_submission_type_still_counts():
    a = _Obj(submission_types=["online_quiz"], quiz_id=99)
    assert quiz_id_of_assignment(a) == 99


def test_an_assignment_with_no_quiz_fields_at_all_is_safe():
    assert quiz_id_of_assignment(_Obj()) is None


def test_the_regression_the_assignment_copy_no_longer_claims_it_is_empty():
    """THE finding: this body used to be '' and rendered "(No content
    provided)"."""
    body = assignment_body_html(_Course(_Q(raises=_forbidden())), REAL, "")
    assert body.strip() != ""
    assert "does not mean the quiz is empty" in body


def test_an_ordinary_assignment_body_is_untouched():
    a = _Obj(description="x", submission_types=["online_upload"],
             is_quiz_assignment=False)
    assert assignment_body_html(_Course(), a, "<p>Hand in a report.</p>") == \
        "<p>Hand in a report.</p>"


def test_a_quiz_assignment_with_a_description_keeps_it_and_gains_questions():
    a = _Obj(submission_types=["online_quiz"], quiz_id=1, is_quiz_assignment=True)
    body = assignment_body_html(_Course(_Q(raises=_forbidden())), a,
                                "<p>Open book.</p>")
    assert body.startswith("<p>Open book.</p>")
    assert "does not mean the quiz is empty" in body


def test_an_unreachable_quiz_falls_back_without_crashing():
    a = _Obj(submission_types=["online_quiz"], quiz_id=1, is_quiz_assignment=True)
    body = assignment_body_html(_Course(raises=RuntimeError("boom")), a, "")
    assert body.strip() != "", "a fetch failure must not re-create the blank body"


# --------------------------------------------------------------------------
# one implementation, every save site
# --------------------------------------------------------------------------

import re  # noqa: E402

_RAW = (REPO / "core" / "canvas_logic.py").read_text(encoding="utf-8")
# Comments blanked before counting, the same way verify_architecture.py does
# it: the comment explaining WHY there is one call site otherwise counts as a
# second one, and the check that polices the rule fails on its own rationale.
SRC = re.sub(r"^\s*#.*$", "", _RAW, flags=re.M)


def test_questions_are_fetched_in_exactly_one_place():
    """They were fetched in one of five save sites, which is how a quiz saved
    any other way ended up blank."""
    assert SRC.count("get_questions()") == 1


def test_every_quiz_save_site_writes_the_full_body():
    assert SRC.count("quiz_body_html(quiz, debug_file)") == 3


def test_every_assignment_save_site_routes_through_the_helper():
    assert SRC.count("assignment_body_html(") == 4      # 3 call sites + the def
