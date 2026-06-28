"""Panopto integration package for Canvas Downloader.

Premium hidden feature: discovers Panopto recordings linked in a Canvas
course, downloads their audio, and transcribes them locally with faster-whisper.

Submodules
----------
settings    : load/save the user's Panopto configuration (engine config persisted
              in the main settings JSON under the ``"panopto"`` key; output/layout
              are per-run contracts).
models      : faster-whisper model registry + on-demand download/install/delete.
auth        : Canvas -> Panopto LTI 1.3 / OIDC handshake (host-agnostic).
discovery   : scan a Canvas course for linked Panopto recordings.
stream      : DeliveryInfo stream resolution + audio/video download via ffmpeg.
transcribe  : local faster-whisper transcription (crash-isolated subprocess).
hardware    : compute-hardware detection (CPU / NVIDIA-CUDA GPU).
cuda_provision : opt-in CUDA library provisioning for GPU transcription (Windows).
runner      : phased batch orchestration (discover -> download -> transcribe).
sync_plan   : classify discovered recordings against disk for the sync engine.
"""
