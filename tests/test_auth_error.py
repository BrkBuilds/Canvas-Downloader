from __future__ import annotations

import pytest
from core.canvas_logic import is_auth_error
from canvasapi.exceptions import Unauthorized

class DummyException(Exception):
    pass

class DummyWithStatus(Exception):
    def __init__(self, message, status_code):
        super().__init__(message)
        self.status_code = status_code

def test_is_auth_error_none():
    assert is_auth_error(None) is False

def test_is_auth_error_unauthorized_instance():
    # Mocking standard requests response for Unauthorized
    class MockResponse:
        status_code = 401
        reason = "Unauthorized"
        text = "Unauthorized"
        url = "https://example.com"
        
    response = MockResponse()
    exc = Unauthorized(response)
    assert is_auth_error(exc) is True

def test_is_auth_error_status_code():
    exc = DummyWithStatus("Some error", 401)
    assert is_auth_error(exc) is True
    
    exc_forbidden = DummyWithStatus("Forbidden", 403)
    assert is_auth_error(exc_forbidden) is False

def test_is_auth_error_keywords():
    assert is_auth_error(DummyException("expired access token")) is True
    assert is_auth_error(DummyException("Expired access token.")) is True
    assert is_auth_error(DummyException("unauthorized request")) is True
    assert is_auth_error(DummyException("user not authorised")) is True
    assert is_auth_error(DummyException("invalid access token")) is True
    assert is_auth_error(DummyException("401 error")) is True
    assert is_auth_error(DummyException("some generic error")) is False
