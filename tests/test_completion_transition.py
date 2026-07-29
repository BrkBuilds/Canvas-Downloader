"""Guards the download -> completion / sync -> completion transition.

The transition used to render as a broken screen: the run's terminal log and
metrics row appeared INSIDE the completion card, the folder cards stacked up
underneath, and then the card shrank and everything jumped up (~1s, and the
retry pass made it obvious because the download itself took half a second).

Two independent causes, one test file:

1. Streamlit reconciles by POSITION and ``AppRoot.addBlock`` hands a block
   landing on another block's index that block's CHILDREN. The completion card
   sat on the run dashboard's index. Fixed by emitting an ``st.empty()`` first
   so the card lands one slot later - see ``shared.components.fresh_container``.
   (Verified in the browser; what is testable here is that the helper really
   emits the empty at a DIFFERENT index than the container, because doing it at
   the same index is silently useless - ForwardMsgQueue composes two deltas at
   one path into the last one.)

2. ``CanvasManager.__init__`` does a blocking HTTPS round-trip to resolve
   vanity URLs, and the completion screen built one manager PER COURSE, twice
   over, purely to reach ``_sanitize_filename``. That is the second of blocking
   I/O the screen spent streaming itself in.
"""

import pytest

import core.canvas_logic as canvas_logic
from core.canvas_logic import CanvasManager


# ── Vanity-URL resolution is memoised ───────────────────────────────────────

@pytest.fixture
def clear_url_cache():
    canvas_logic._RESOLVED_CANVAS_URLS.clear()
    yield
    canvas_logic._RESOLVED_CANVAS_URLS.clear()


class _FakeResponse:
    def __init__(self, url):
        self.url = url
        self.history = []


def test_repeat_construction_makes_one_http_call(monkeypatch, clear_url_cache):
    """The completion screen constructs several managers; only the first may
    touch the network. Before the cache this was 2 blocking round-trips per
    course on a screen that is supposed to appear instantly."""
    calls = []

    def _fake_get(url, **kw):
        calls.append(url)
        return _FakeResponse(url)

    monkeypatch.setattr(canvas_logic.requests, 'get', _fake_get)

    for _ in range(5):
        CanvasManager('tok', 'https://canvas.myschool.edu')

    assert len(calls) == 1


def test_canonical_host_never_touches_the_network(monkeypatch, clear_url_cache):
    """A URL that already IS an instructure.com host has nothing to resolve.

    Resolution exists to follow a vanity domain to its instructure.com target,
    so pointing it at the target can only return what it was given. It ran
    anyway - a full fetch of the Canvas landing page, measured at 0.70s, on the
    startup path before a single pixel of UI existed.
    """
    monkeypatch.setattr(
        canvas_logic.requests, 'get',
        lambda *a, **k: pytest.fail('resolved a URL that was already canonical'))

    for url in ('https://example.instructure.com',
                'https://EXAMPLE.Instructure.com',      # host match is case-insensitive
                'http://instructure.com'):
        assert CanvasManager('tok', url).api_url.lower().endswith('instructure.com')


def test_lookalike_hosts_are_still_resolved(monkeypatch, clear_url_cache):
    """The fast path matches the HOST, so a domain that merely CONTAINS
    'instructure.com' is not mistaken for one - it is a vanity host like any
    other and still gets resolved."""
    seen = []
    monkeypatch.setattr(canvas_logic.requests, 'get',
                        lambda url, **kw: (seen.append(url), _FakeResponse(url))[1])

    CanvasManager('tok', 'https://foo.instructure.com.example.net')
    CanvasManager('tok', 'https://instructure.com.example.net')

    assert seen == ['https://foo.instructure.com.example.net',
                    'https://instructure.com.example.net']


def test_resolved_vanity_url_is_reused(monkeypatch, clear_url_cache):
    """A vanity host that redirects must keep resolving to the real domain on
    later constructions, not fall back to the vanity host."""
    def _fake_get(url, **kw):
        res = _FakeResponse('https://real.instructure.com/')
        res.history = [_FakeResponse('https://real.instructure.com/')]
        return res

    monkeypatch.setattr(canvas_logic.requests, 'get', _fake_get)

    first = CanvasManager('tok', 'https://canvas.myschool.edu')
    monkeypatch.setattr(canvas_logic.requests, 'get',
                        lambda *a, **k: pytest.fail('second construction hit the network'))
    second = CanvasManager('tok', 'https://canvas.myschool.edu')

    assert first.api_url == 'https://real.instructure.com'
    assert second.api_url == first.api_url


def test_failed_resolution_is_not_cached(monkeypatch, clear_url_cache):
    """A resolution that failed because the network was down must be retried,
    not remembered as 'this host does not redirect'."""
    attempts = []

    def _boom(url, **kw):
        attempts.append(url)
        raise OSError('network down')

    monkeypatch.setattr(canvas_logic.requests, 'get', _boom)
    CanvasManager('tok', 'https://canvas.myschool.edu')
    CanvasManager('tok', 'https://canvas.myschool.edu')

    assert len(attempts) == 2


def test_different_urls_are_cached_separately(monkeypatch, clear_url_cache):
    seen = []
    monkeypatch.setattr(canvas_logic.requests, 'get',
                        lambda url, **kw: (seen.append(url), _FakeResponse(url))[1])

    CanvasManager('tok', 'https://canvas.a-school.edu')
    CanvasManager('tok', 'https://canvas.b-school.edu')
    CanvasManager('tok', 'https://canvas.a-school.edu')

    assert seen == ['https://canvas.a-school.edu', 'https://canvas.b-school.edu']


# ── fresh_container must SHIFT the index, not reuse it ──────────────────────

def test_fresh_container_emits_empty_at_its_own_index():
    """``placeholder.container()`` would put both deltas on ONE delta path, and
    ForwardMsgQueue composes those into the last one - the empty never reaches
    the browser and the children are inherited exactly as before. The helper
    must therefore call ``st.empty()`` and ``st.container()`` as two separate
    top-level calls."""
    import inspect

    from shared.components import fresh_container

    src = inspect.getsource(fresh_container)
    body = src.split('"""')[-1]

    assert 'st.empty()' in body, 'fresh_container must emit a leading st.empty()'
    assert 'st.container(' in body
    # The failure mode this guards: slot = st.empty(); slot.container(...)
    assert '.container(' not in body.replace('st.container(', ''), (
        'the container must not be created from the placeholder - same delta '
        'path means the empty is composed away'
    )
