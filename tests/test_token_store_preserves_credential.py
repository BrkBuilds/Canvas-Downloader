"""A failed token save must not destroy the token that was already saved.

Found on real macOS 15 hardware, 2026-08-10, by the live audit - and measured
against the real library rather than reasoned about:

    keyring.set_password(SVC, USER, "probe-value-before")   -> stored
    keyring.set_password(SVC, USER, "probe-value-AFTER")    -> PasswordSetError
                                                               (-25308)
    keyring.get_password(SVC, USER)                          -> None

The macOS backend DELETES any existing item before adding the new one, so a
refused write leaves nothing behind. Three things then combined in ui/auth.py:

  * ``_safe_keyring_set`` RETURNS False instead of raising, so the login flow's
    ``except Exception`` amber notice was unreachable for this failure;
  * ``_save_fallback_token`` returns immediately off Windows - by design, the
    app must not put tokens on disk - so macOS had no second copy;
  * the only trace was ``logger.warning("... Saved to DPAPI-encrypted fallback
    storage.")``, which on macOS describes a save that did not happen.

Net effect: a working saved login vanished, the next launch showed the login
page, and nothing on screen ever said why. Worse at the two legacy-migration
sites, which popped the token out of ``canvas_downloader_settings.json`` and
rewrote the file whatever the keyring returned - that being the one run where
the JSON copy is the only copy.

``ui.auth.store_token`` is the fix: skip a write that cannot change anything,
then write, then VERIFY by reading back, so its return value describes the
stored state rather than the return code of one attempt.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


class FakeKeyring:
    """Enough of the keyring API for ui.auth, with a switchable write refusal."""

    class errors:                                                # noqa: N801
        class PasswordSetError(Exception):
            pass

        class PasswordDeleteError(Exception):
            pass

    def __init__(self, *, refuse_writes: bool = False,
                 destructive: bool = True, refuse_reads: bool = False):
        self.store: dict[tuple[str, str], str] = {}
        self.refuse_writes = refuse_writes
        # True mirrors macOS: the delete happens before the add, so a refused
        # write also destroys what was there.
        self.destructive = destructive
        self.refuse_reads = refuse_reads
        self.set_calls = 0
        self.get_calls = 0

    def get_password(self, service, user):
        self.get_calls += 1
        if self.refuse_reads:
            raise RuntimeError("keychain unavailable")
        return self.store.get((service, user))

    def set_password(self, service, user, password):
        self.set_calls += 1
        if self.refuse_writes:
            if self.destructive:
                self.store.pop((service, user), None)
            raise self.errors.PasswordSetError(
                "Can't store password on keychain: (-25308, 'Unknown Error')")
        self.store[(service, user)] = password

    def delete_password(self, service, user):
        self.store.pop((service, user), None)


@pytest.fixture
def auth(monkeypatch):
    """ui.auth with keyring faked at the module level it imports it from.

    ``_safe_keyring_get`` / ``_safe_keyring_set`` do `import keyring` inside the
    function, so replacing sys.modules['keyring'] means the REAL wrappers,
    watchdog thread included, run against the fake - which is the point: the
    thing under test is store_token's ordering, not a re-implementation of it.
    """
    from ui import auth as _auth
    fake = FakeKeyring()
    monkeypatch.setitem(sys.modules, "keyring", fake)
    # No disk fallback anywhere in these tests: the macOS shape is the one that
    # loses data, and a Windows DPAPI write would mask it.
    monkeypatch.setattr(_auth, "_save_fallback_token", lambda *a, **k: None)
    monkeypatch.setattr(_auth, "_load_fallback_token", lambda *a, **k: None)
    _auth._fake = fake                                            # test handle
    return _auth


USER = "https://example.instructure.com"


def test_an_unchanged_token_is_never_rewritten(auth):
    """THE regression. A re-login with the same token must not touch the store.

    This is the case that turns a refused write into data loss for a user who
    had a perfectly good credential, and it is also the common case - so the
    cheapest correct answer is not to write at all.
    """
    fake = auth._fake
    fake.store[(auth.KEYRING_SERVICE, USER)] = "tok-A"
    fake.refuse_writes = True

    assert auth.store_token(USER, "tok-A") is True
    assert fake.set_calls == 0, "an identical token must not be re-written"
    assert fake.store[(auth.KEYRING_SERVICE, USER)] == "tok-A", (
        "the credential that was already stored must survive")


def test_a_refused_write_of_a_new_token_reports_failure(auth):
    """The honest-answer half: nothing holds the token, so say so.

    The old code returned no signal a caller could act on - the login flow's
    only reaction was a log line claiming a DPAPI save.
    """
    fake = auth._fake
    fake.refuse_writes = True
    assert auth.store_token(USER, "tok-NEW") is False
    assert fake.set_calls >= 1, "a genuinely new token must be attempted"


def test_a_successful_write_reports_success_and_is_readable(auth):
    fake = auth._fake
    assert auth.store_token(USER, "tok-NEW") is True
    assert fake.store[(auth.KEYRING_SERVICE, USER)] == "tok-NEW"


def test_success_is_decided_by_a_READ_BACK_not_by_the_write_returning(auth):
    """A backend that accepts the write and stores nothing must report failure.

    Not hypothetical for this app: ``_safe_keyring_set`` also returns False on a
    watchdog TIMEOUT, where the native call may still be in flight - so "the
    call came back" and "the token is retrievable" are genuinely different
    questions, and only the second one lets a caller delete its own copy.
    """
    fake = auth._fake

    def silently_drop(service, user, password):
        fake.set_calls += 1

    fake.set_password = silently_drop
    assert auth.store_token(USER, "tok-NEW") is False


def test_an_unreadable_store_does_not_claim_success(auth):
    """With reads failing there is no way to confirm anything: answer False."""
    fake = auth._fake
    fake.refuse_reads = True
    fake.refuse_writes = True
    assert auth.store_token(USER, "tok-NEW") is False


def test_store_token_never_raises(auth):
    """A persistence failure must not be able to abort a login."""
    fake = auth._fake

    def explode(*a, **k):
        raise RuntimeError("backend on fire")

    fake.get_password = explode
    fake.set_password = explode
    assert auth.store_token(USER, "tok") is False


def test_store_token_survives_the_WRAPPER_itself_raising(auth, monkeypatch):
    """The failure store_token's own try/except exists for.

    ``_safe_keyring_set`` swallows backend errors and returns False, which makes
    the guard around it look redundant - a mutation removing it survived a first
    pass for exactly that reason. It is not redundant: that wrapper does
    ``import keyring`` OUTSIDE its own try, so a broken or excluded keyring
    package raises ImportError straight through it. Injected directly here,
    which is the point - the property is "nothing gets out of store_token",
    whatever the layer below does.
    """
    def explode(*a, **k):
        raise ImportError("No module named 'keyring'")

    monkeypatch.setattr(auth, "_safe_keyring_set", explode)
    monkeypatch.setattr(auth, "_safe_keyring_get", explode)
    assert auth.store_token(USER, "tok") is False


# ── the call sites ────────────────────────────────────────────────────────────

def _auth_tree() -> ast.Module:
    return ast.parse((REPO / "ui" / "auth.py").read_text(encoding="utf-8"))


def _calls_named(node: ast.AST, name: str) -> list[ast.Call]:
    return [n for n in ast.walk(node)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == name]


def test_no_call_site_writes_the_keyring_directly_any_more():
    """Only store_token may call _safe_keyring_set.

    A second, bare call site is how this defect would come back: it would look
    finished (the write is attempted) while skipping the skip-if-identical and
    the read-back that make it safe.
    """
    tree = _auth_tree()
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef):
            continue
        if fn.name in ("store_token", "_safe_keyring_set"):
            continue
        assert not _calls_named(fn, "_safe_keyring_set"), (
            f"{fn.name}() writes the keyring directly; route it through "
            f"store_token so an unchanged token is not re-written")


def test_both_legacy_migrations_only_drop_the_json_copy_on_success():
    """`config.pop('<token field>')` must be guarded by store_token.

    These two branches move a token out of the settings file, so the JSON copy
    is the only copy in existence at that moment. Asserted structurally because
    the code lives inside restore_saved_session, which needs a live Streamlit
    session to execute.
    """
    tree = _auth_tree()
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef)
              and n.name == "restore_saved_session")

    popped_fields = {"mac_api_token", "api_token"}
    seen: set[str] = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.If):
            continue
        if not _calls_named(node.test, "store_token"):
            continue
        for inner in ast.walk(node):
            if (isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr == "pop"
                    and inner.args
                    and isinstance(inner.args[0], ast.Constant)
                    and inner.args[0].value in popped_fields):
                seen.add(inner.args[0].value)
    assert seen == popped_fields, (
        f"legacy token fields dropped outside a store_token guard: "
        f"{popped_fields - seen}")


def test_a_failed_save_tells_the_USER_not_only_the_log():
    """The whole reason this was invisible: the only trace was a log line.

    A user whose keychain refused the write is about to be logged out on the
    next launch, and their token is the one thing they need to have kept.
    """
    src = (REPO / "ui" / "auth.py").read_text(encoding="utf-8")
    i = src.index("kr_success = store_token(")
    window = src[i:i + 2000]
    assert "render_amber_notice" in window, (
        "the login flow must surface a failed token save on screen")
    assert "DPAPI-encrypted fallback storage" not in window, (
        "that message claims a save that does not happen off Windows")
