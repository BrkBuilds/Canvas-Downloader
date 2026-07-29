"""Canvas Downloader live audit suite.

A real-life, repeatable audit of the running application: it launches the app,
drives it through a browser the way a user would, runs genuine downloads and
syncs against real Canvas courses, and then reconciles what it sees against
five independent views of the same truth.

This is deliberately NOT a unit-test suite. ``tests/test_*.py`` proves that
individual functions behave; this proves that the assembled product delivers
the right files to the right places and tells the user the truth about it.

Entry point is the CLI: ``python -m tests.audit --help``. The manuscript the
agent follows is ``tests/audit/RUNBOOK.md``.
"""
