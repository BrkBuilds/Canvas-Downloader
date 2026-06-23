"""Panopto integration package for Canvas Downloader.

Premium hidden feature: discovers Panopto lecture videos linked in a Canvas
course, downloads their audio, and transcribes them locally with faster-whisper.

Submodules
----------
settings   : load/save the user's Panopto configuration (persisted in the main
             settings JSON under the ``"panopto"`` key).
models     : faster-whisper model registry + on-demand download/install/delete.

Phase 2 (not yet present) will add: auth (LTI handshake), discovery, stream,
transcribe, runner.
"""
