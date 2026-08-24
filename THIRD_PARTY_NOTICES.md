# Third-Party Notices

Canvas Downloader itself is licensed under the **GNU General Public License v3** (see
[LICENSE](LICENSE)). It also ships and depends on third-party components, listed here with their
own licenses. Nothing below changes the terms of the components themselves.

---

## FFmpeg (bundled binary) - GPL v3

Both the Windows and macOS builds bundle an FFmpeg executable, supplied by the
[`imageio-ffmpeg`](https://github.com/imageio/imageio-ffmpeg) package. The binary currently shipped
reports itself as:

    7.1-essentials_build-www.gyan.dev

These "essentials" builds are compiled with GPL-licensed components (libx264, libx265) and are
therefore distributed under the **GNU General Public License v3**, the same license as this
application.

Canvas Downloader invokes FFmpeg as a **separate process** (command-line arguments over a
subprocess), never by linking against its libraries. It is used to extract audio from lecture
recordings and to download Panopto streams.

**Where to get the source.** FFmpeg's complete corresponding source is published by the FFmpeg
project and by the build's packager:

- FFmpeg upstream source: <https://ffmpeg.org/download.html> and <https://git.ffmpeg.org/ffmpeg.git>
- Build configuration and sources for the shipped build: <https://www.gyan.dev/ffmpeg/builds/>

If you need the exact corresponding source for the binary in a specific release and cannot obtain it
from the links above, open an issue and it will be provided.

---

## PyInstaller (build tool + bootloader)

Releases are packaged with [PyInstaller](https://pyinstaller.org/), which is GPL v2-or-later **with
a bootloader exception**. That exception explicitly permits distributing the resulting bundled
application under any license, so it places no additional obligation on Canvas Downloader or on
anyone redistributing it.

---

## Python dependencies

All of the following are permissively licensed (MIT, BSD, Apache-2.0 or PSF) and are compatible
with GPL v3. Versions are pinned in [requirements.txt](requirements.txt).

| Component | License |
|---|---|
| Streamlit | Apache-2.0 |
| Tornado | Apache-2.0 |
| requests | Apache-2.0 |
| aiohttp | Apache-2.0 |
| aiofiles | Apache-2.0 |
| huggingface_hub | Apache-2.0 |
| tokenizers | Apache-2.0 |
| canvasapi | MIT |
| beautifulsoup4 | MIT |
| markdownify | MIT |
| moviepy | MIT |
| openpyxl | MIT |
| keyring | MIT |
| win11toast | MIT |
| faster-whisper | MIT |
| CTranslate2 | MIT |
| ONNX Runtime | MIT |
| Pillow | MIT-CMU |
| imageio | BSD-2-Clause |
| imageio-ffmpeg (the Python wrapper) | BSD-2-Clause |
| psutil | BSD-3-Clause |
| pywebview | BSD-3-Clause |
| NumPy | BSD-3-Clause |
| pandas | BSD-3-Clause |
| protobuf | BSD-3-Clause |
| Altair | BSD-3-Clause |
| pywin32 | PSF |
| pync (macOS, no longer bundled) | MIT |

Apache-2.0 is one-way compatible with GPL **v3** but not with GPL v2. That is one reason this
project is licensed under v3 specifically.

### Vendored native components inside those wheels

Two of the wheels above ship compiled components under copyleft licenses that carry an explicit
exemption. Neither places a copyleft obligation on Canvas Downloader, but both are recorded here
because a compliance file should name what is actually in the box.

**FreeType 2** (inside Pillow) is dual-licensed under the FreeType License (FTL) **or** GPL v2.
This project uses it under the **FTL**, which requires the following credit:

> Portions of this software are copyright (c) The FreeType Project (<https://www.freetype.org>).
> All rights reserved.

**GCC runtime library** (libgcc / libgfortran / libquadmath, inside NumPy) is GPL v3 **with the GCC
Runtime Library Exception**. That exception grants permission to convey the combined work under
terms of your choice, so it imposes no additional condition here.

### Optional, downloaded on demand (not bundled)

These are fetched into the app's config directory only if the user opts in, and are never
redistributed as part of a release:

| Component | License |
|---|---|
| Whisper model weights (via Hugging Face) | per-model, see the model card |
| NVIDIA cuBLAS / cuDNN / CUDA runtime wheels | NVIDIA proprietary EULA |

---

## Canvas and Panopto

Canvas Downloader is an independent project. It is not affiliated with, endorsed by, or sponsored
by Instructure, Inc. (Canvas LMS) or Panopto, Inc. Those names are used only to describe what the
software interoperates with, and remain the trademarks of their respective owners. See
[DISCLAIMER.md](DISCLAIMER.md).
