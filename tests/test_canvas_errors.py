"""Tests for humanize_canvas_error - the guard that keeps raw Canvas error
payloads (Python dict reprs) out of the user interface.

Regression context: an expired saved token is the single most common failure in
the app's lifetime. canvasapi's Unauthorized carries the PARSED JSON body, so
str(exc) is "[{'message': 'Invalid access token.'}]" - a Python repr. That was
being rendered verbatim on the login screen as "Technical Details", and because
the repr contains none of "invalid token"/"unauthorized"/"401" the login screen's
keyword routing never recognised it as an auth failure at all.
"""

import pytest

from canvasapi.exceptions import (
    CanvasException,
    Forbidden,
    ResourceDoesNotExist,
    Unauthorized,
)

from core.canvas_logic import humanize_canvas_error


class TestHumanizeCanvasError:
    def test_unauthorized_list_payload(self):
        exc = Unauthorized([{"message": "Invalid access token."}])
        assert humanize_canvas_error(exc) == "Invalid access token."

    def test_errors_wrapper_dict(self):
        exc = CanvasException({"errors": [{"message": "Invalid access token."}]})
        assert "Invalid access token." in humanize_canvas_error(exc)

    def test_field_keyed_errors_dict(self):
        exc = CanvasException({"errors": {"end_date": [{"message": "must be after start"}]}})
        assert humanize_canvas_error(exc) == "must be after start"

    def test_tuple_payload_from_plain_canvas_exception(self):
        """Plain CanvasException wraps its body in a tuple, so the repr starts
        with '(' - the parser must accept that too, not only '{' and '['."""
        out = humanize_canvas_error(CanvasException({"message": "Something broke"}))
        assert "Something broke" in out
        assert "{" not in out and "}" not in out

    def test_duplicate_messages_are_collapsed(self):
        exc = CanvasException({"errors": [{"message": "A"}, {"message": "A"}, {"message": "B"}]})
        assert humanize_canvas_error(exc) == "A B"

    @pytest.mark.parametrize("exc", [
        CanvasException("plain string error"),
        ResourceDoesNotExist("Not Found"),
        ValueError("not a canvas error at all"),
    ])
    def test_non_payload_errors_pass_through(self, exc):
        assert humanize_canvas_error(exc) == str(exc)

    def test_forbidden(self):
        exc = Forbidden([{"message": "user not authorized to perform that action"}])
        assert humanize_canvas_error(exc) == "user not authorized to perform that action"

    def test_never_leaks_a_repr(self):
        """No output may contain dict/list punctuation - that is the whole point."""
        payloads = [
            Unauthorized([{"message": "Invalid access token."}]),
            CanvasException({"errors": [{"message": "Bad request"}]}),
            CanvasException({"errors": {"f": [{"message": "nope"}]}}),
        ]
        for exc in payloads:
            out = humanize_canvas_error(exc)
            assert not any(ch in out for ch in "{}[]"), out
            assert "'" not in out, out

    def test_empty_and_none_are_safe(self):
        assert humanize_canvas_error(None) == ""
        assert humanize_canvas_error(CanvasException("")) == ""


class TestValidateTokenMessage:
    """The message validate_token returns for an expired token must be routable
    by ui/auth.py's keyword matching, or the login screen falls back to its
    generic "Technical Details" branch."""

    AUTH_KEYWORDS = [
        "revoked", "invalid token", "invalid access token",
        "access token is invalid", "unauthorized", "401",
    ]

    def test_unauthorized_message_routes_to_auth_branch(self):
        from core.canvas_logic import CanvasManager

        class _FakeCanvas:
            def get_current_user(self):
                raise Unauthorized([{"message": "Invalid access token."}])

        cm = CanvasManager.__new__(CanvasManager)
        cm.api_url = "https://example.instructure.com"
        cm.canvas = _FakeCanvas()

        ok, message = cm.validate_token()
        assert ok is False
        low = message.lower()
        assert any(k in low for k in self.AUTH_KEYWORDS), message
        # and it must not be a raw repr
        assert not any(ch in message for ch in "{}[]"), message
