"""Tests for the Submissions (Results) feature - submission FEEDBACK download.

Context: the "Submissions (Results)" card shipped with a fully live UI, a green
confirmation badge and 6 presets enabling it, but no engine implementation at all
- `download_submissions` had exactly one reference in the whole engine (its
default-dict entry). These tests cover the implementation added 2026-07-25.

The standing architectural decision under test: the app downloads the FEEDBACK on
a submission (grade, rubric assessment, teacher comments and any files attached to
those comments) and deliberately NEVER downloads the student's own submitted
files, which they already have locally.
"""

import types

import pytest

from core.canvas_logic import (
    CanvasManager,
    _submission_comment_attachments,
    _submission_has_feedback,
    compute_entity_content_sig,
)
from core.sync_manager import make_secondary_id, secondary_id_type


def _sub(**kw):
    """A submission stub with the fields the engine reads."""
    base = dict(
        assignment_id=555,
        assignment={'id': 555, 'name': 'Essay 1', 'points_possible': 100,
                    'html_url': 'https://x.instructure.com/courses/1/assignments/555'},
        entered_grade=None, grade=None, entered_score=None, score=None,
        graded_at=None, workflow_state='unsubmitted',
        submission_comments=[], rubric_assessment=None,
        attachments=[], late=False, missing=False, excused=False,
        submitted_at=None, attempt=None, body=None,
    )
    base.update(kw)
    return types.SimpleNamespace(**base)


class TestHasFeedback:
    def test_nothing_is_not_feedback(self):
        assert _submission_has_feedback(_sub()) is False

    def test_none_is_safe(self):
        assert _submission_has_feedback(None) is False

    def test_letter_grade_counts(self):
        assert _submission_has_feedback(_sub(entered_grade='B+')) is True

    def test_zero_score_counts(self):
        """A score of 0 is real feedback - it must not be falsy-filtered away."""
        assert _submission_has_feedback(_sub(score=0)) is True

    def test_rubric_counts(self):
        assert _submission_has_feedback(
            _sub(rubric_assessment={'crit_1': {'points': 8}})) is True

    def test_comment_counts(self):
        assert _submission_has_feedback(
            _sub(submission_comments=[{'comment': 'Nice work'}])) is True

    def test_blank_comment_does_not_count(self):
        assert _submission_has_feedback(
            _sub(submission_comments=[{'comment': '   '}])) is False

    def test_submitting_without_feedback_does_not_count(self):
        """Handing something in is not feedback - otherwise every submitted
        assignment in the course would produce a 'not graded yet' file."""
        assert _submission_has_feedback(
            _sub(workflow_state='submitted', submitted_at='2026-05-01T10:00:00Z',
                 attempt=1, attachments=[{'id': 9, 'url': 'u'}])) is False


class TestCommentAttachments:
    def test_own_submission_attachments_are_never_returned(self):
        """The core architectural decision, asserted directly."""
        sub = _sub(attachments=[{'id': 111, 'url': 'https://x/my-essay.docx',
                                 'filename': 'my-essay.docx'}])
        assert _submission_comment_attachments(sub) == []

    def test_teacher_comment_attachment_is_returned(self):
        sub = _sub(submission_comments=[{
            'id': 1, 'comment': 'See annotations',
            'attachments': [{'id': 222, 'url': 'https://x/annotated.pdf',
                             'filename': 'annotated.pdf',
                             'display_name': 'annotated.pdf', 'size': 4096,
                             'content-type': 'application/pdf'}],
        }])
        out = _submission_comment_attachments(sub)
        assert len(out) == 1
        assert out[0]['id'] == 222
        assert out[0]['filename'] == 'annotated.pdf'
        assert out[0]['size'] == 4096

    def test_same_attachment_on_two_comments_is_deduped(self):
        att = {'id': 333, 'url': 'https://x/f.pdf', 'filename': 'f.pdf'}
        sub = _sub(submission_comments=[
            {'id': 1, 'comment': 'a', 'attachments': [att]},
            {'id': 2, 'comment': 'b', 'attachments': [att]},
        ])
        assert len(_submission_comment_attachments(sub)) == 1

    def test_attachment_without_url_is_skipped(self):
        sub = _sub(submission_comments=[
            {'id': 1, 'comment': 'x', 'attachments': [{'id': 444}]}])
        assert _submission_comment_attachments(sub) == []

    def test_object_style_comments(self):
        """canvasapi hands comments back as objects on some endpoints."""
        att = types.SimpleNamespace(id=555, url='https://x/o.pdf', filename='o.pdf',
                                    display_name='o.pdf', size=1,
                                    updated_at='', content_type='application/pdf')
        comment = types.SimpleNamespace(id=1, comment='hi', attachments=[att])
        out = _submission_comment_attachments(_sub(submission_comments=[comment]))
        assert len(out) == 1 and out[0]['id'] == 555


class TestContentSignature:
    def test_regrade_changes_the_signature(self):
        a = compute_entity_content_sig('submission', _sub(entered_grade='C', score=60))
        b = compute_entity_content_sig('submission', _sub(entered_grade='A', score=95))
        assert a != b

    def test_new_comment_changes_the_signature(self):
        a = compute_entity_content_sig('submission', _sub(
            submission_comments=[{'id': 1, 'comment': 'first'}]))
        b = compute_entity_content_sig('submission', _sub(
            submission_comments=[{'id': 1, 'comment': 'first'},
                                 {'id': 2, 'comment': 'second'}]))
        assert a != b

    def test_edited_comment_changes_the_signature(self):
        a = compute_entity_content_sig('submission', _sub(
            submission_comments=[{'id': 1, 'comment': 'ok'}]))
        b = compute_entity_content_sig('submission', _sub(
            submission_comments=[{'id': 1, 'comment': 'ok, but see p.2'}]))
        assert a != b

    def test_rubric_change_changes_the_signature(self):
        a = compute_entity_content_sig('submission', _sub(
            rubric_assessment={'c1': {'points': 5, 'comments': ''}}))
        b = compute_entity_content_sig('submission', _sub(
            rubric_assessment={'c1': {'points': 9, 'comments': ''}}))
        assert a != b

    def test_resubmitting_does_NOT_change_the_signature(self):
        """A new attempt is the student's own doing. If it moved the signature the
        sync engine would report the teacher's feedback as changed and re-download
        an identical file on every sync."""
        graded = dict(entered_grade='B', score=80, graded_at='2026-05-02T09:00:00Z',
                      workflow_state='graded')
        a = compute_entity_content_sig('submission', _sub(
            **graded, submitted_at='2026-05-01T10:00:00Z', attempt=1))
        b = compute_entity_content_sig('submission', _sub(
            **graded, submitted_at='2026-05-09T23:59:00Z', attempt=2,
            attachments=[{'id': 1, 'url': 'u'}]))
        assert a == b

    def test_rubric_key_order_is_irrelevant(self):
        a = compute_entity_content_sig('submission', _sub(
            rubric_assessment={'c1': {'points': 1}, 'c2': {'points': 2}}))
        b = compute_entity_content_sig('submission', _sub(
            rubric_assessment={'c2': {'points': 2}, 'c1': {'points': 1}}))
        assert a == b

    def test_signature_is_stable_across_calls(self):
        s = _sub(entered_grade='A', submission_comments=[{'id': 1, 'comment': 'x'}])
        assert (compute_entity_content_sig('submission', s)
                == compute_entity_content_sig('submission', s))


class TestSyntheticIdBand:
    def test_submission_ids_live_in_their_own_band(self):
        sid = make_secondary_id('submission', 12345)
        assert sid == -80012345
        assert secondary_id_type(sid) == 'submission'

    def test_band_does_not_collide_with_neighbours(self):
        for other in ('assignment', 'quiz', 'rubric', 'calendar', 'attachment'):
            assert secondary_id_type(make_secondary_id(other, 1)) == other


class TestFeedbackHtml:
    @pytest.fixture
    def cm(self):
        return CanvasManager.__new__(CanvasManager)

    def test_rubric_and_comments_are_rendered(self, cm):
        sub = _sub(
            rubric_assessment={'Argumentation': {'points': 28, 'comments': 'Strong thesis'}},
            submission_comments=[{'id': 1, 'comment': 'See the PDF.',
                                  'author_name': 'Lars', 'created_at': ''}],
        )
        out = cm._build_submission_feedback_html(sub)
        assert 'Rubric assessment' in out
        assert 'Argumentation' in out and '28' in out and 'Strong thesis' in out
        assert 'Comments' in out and 'See the PDF.' in out and 'Lars' in out

    def test_html_in_a_comment_is_escaped(self, cm):
        sub = _sub(submission_comments=[
            {'id': 1, 'comment': '<script>alert(1)</script>', 'author_name': 'X'}])
        out = cm._build_submission_feedback_html(sub)
        assert '<script>' not in out
        assert '&lt;script&gt;' in out

    def test_graded_with_no_rubric_or_comments_says_so(self, cm):
        out = cm._build_submission_feedback_html(_sub(entered_grade='A'))
        assert 'no rubric assessment or comments' in out.lower()

    def test_blank_comments_are_skipped(self, cm):
        out = cm._build_submission_feedback_html(
            _sub(entered_grade='A', submission_comments=[{'id': 1, 'comment': '  '}]))
        assert 'Comments' not in out


class TestFetchFiltersAndFallback:
    @pytest.fixture
    def cm(self):
        return CanvasManager.__new__(CanvasManager)

    def test_bulk_path_filters_out_submissions_without_feedback(self, cm):
        graded = _sub(entered_grade='A')
        bare = _sub()

        class _Course:
            def get_multiple_submissions(self, **kw):
                assert kw['student_ids'] == ['self']
                assert 'submission_comments' in kw['include']
                assert 'rubric_assessment' in kw['include']
                return [graded, bare]

        out = cm._fetch_submissions_with_feedback(_Course(), None)
        assert out == [graded]

    def test_falls_back_to_per_assignment_when_bulk_is_forbidden(self, cm):
        from canvasapi.exceptions import Forbidden

        graded = _sub(entered_grade='B', assignment=None)

        class _Assignment:
            id = 555
            name = 'Essay 1'
            points_possible = 100
            html_url = 'https://x/a/555'

            def get_submission(self, who, include=None):
                assert who == 'self'
                return graded

        class _Course:
            def get_multiple_submissions(self, **kw):
                raise Forbidden([{'message': 'not allowed'}])

            def get_assignments(self):
                return [_Assignment()]

        out = cm._fetch_submissions_with_feedback(_Course(), None)
        assert out == [graded]
        # the fallback must backfill the assignment so the filename has a title
        assert cm._submission_assignment_field(out[0], 'name') == 'Essay 1'

    def test_total_failure_returns_empty_rather_than_raising(self, cm):
        class _Course:
            def get_multiple_submissions(self, **kw):
                raise RuntimeError('boom')

            def get_assignments(self):
                raise RuntimeError('also boom')

        assert cm._fetch_submissions_with_feedback(_Course(), None) == []
