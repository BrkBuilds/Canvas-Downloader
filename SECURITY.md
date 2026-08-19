# Security policy

## Reporting a vulnerability

Please **do not open a public issue** for a security problem.

Email **brkbuilds1@gmail.com** with the details. Include what you found, how to reproduce it, and
what you think the impact is. You will get a reply, and the fix and the credit will follow.

If you would rather use GitHub, you can open a
[private security advisory](https://github.com/BrkBuilds/Canvas-Downloader/security/advisories/new).

## What is in scope

This is a desktop application with no backend, so the interesting surface is local:

- Anything that could expose or leak a user's **Canvas access token**, including logs, crash
  reports, temporary files or the DPAPI fallback store on Windows.
- **Path traversal** or any archive member, Canvas filename or Panopto title that can write outside
  the folder the user chose.
- **Code injection** through Canvas-controlled data: HTML rendered into the UI, AppleScript string
  literals on macOS, or anything interpolated into a shell or COM call.
- The local Streamlit server on `127.0.0.1`, and anything that widens its reach beyond the machine.
- **Data loss**: anything that can delete or overwrite a user's own file. This project treats the
  user's edited copy as sacred, so a path that destroys one is a security-grade bug even when no
  attacker is involved.

## What is not in scope

- **The unsigned installer warning** on Windows SmartScreen and macOS Gatekeeper. This is known and
  documented. Code-signing certificates cost more than a free student project can carry. The
  Microsoft Store build is signed.
- **Localhost reachability on a shared computer.** The app binds to `127.0.0.1`, which is reachable
  by other users signed in to the same machine at the same time. This is documented in the README
  and the recommendation is to use a personal device.
- Anything requiring an attacker to already have full control of the user's account or machine.
- Vulnerabilities in Canvas itself or in Panopto. Report those to your institution or to
  Instructure.

## Supported versions

Fixes go into the latest release. Please update before reporting, in case what you found is already
fixed.

| Version | Supported |
|---|---|
| Latest release | Yes |
| Anything older | No, please update |

## How the app handles your data

For context when assessing a report:

- The access token is stored in the OS keyring: Windows Credential Manager or the macOS Keychain. On
  Windows there is an encrypted DPAPI fallback whose ciphertext is bound to the Windows user
  account. macOS deliberately has no disk fallback.
- There is no backend, no account system, no analytics and no telemetry. The app contacts your
  institution's Canvas, optionally your institution's Panopto, and for optional one-time downloads
  Hugging Face (transcription models), NVIDIA (CUDA libraries) and this repository's releases
  endpoint (version check).
- Lecture transcription runs entirely on the user's machine. Audio is never uploaded.
- Debug logs redact Bearer tokens and signed download-URL verifiers before writing to disk.
