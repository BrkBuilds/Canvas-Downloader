<p align="center">
  <img src="assets/icon.png" width="120" alt="Canvas Downloader">
</p>

<h1 align="center">Canvas Downloader — Installation Guide</h1>

<p align="center">
  <em>Batch-download all your Canvas LMS course files in seconds.</em>
</p>

---

## Getting Started

1. **Download** the latest release for your operating system from the [Releases](https://github.com/birkls/Canvas_LMS_batch_file_downloader/releases) page.
2. **Extract** the ZIP archive to any location on your computer.
3. **Launch** the application:
   - **Windows**: Double-click `Canvas_Downloader.exe`
   - **macOS**: Double-click `Canvas Downloader.app`

> **First Launch**: The app runs a small local web server to display its interface. Your operating system may ask you to allow network access — this is normal and safe. The app only communicates with `localhost` and the official Canvas API.

---

## ⚠️ Security Warnings — Please Read

Canvas Downloader is an **independent, open-source application**. It is not signed with a paid Microsoft or Apple developer certificate. Because of this, your operating system will display a one-time security warning when you first launch it.

**The application is completely safe.** You can verify the source code yourself on [GitHub](https://github.com/birkls/Canvas_LMS_batch_file_downloader).

---

### 🪟 Windows — SmartScreen Warning

When you run the `.exe` for the first time, Windows SmartScreen may display a blue dialog saying:

> **"Windows protected your PC"**
> *Microsoft Defender SmartScreen prevented an unrecognized app from starting.*

**How to bypass:**

1. Click **"More info"** (the small text link under the warning message).
2. A **"Run anyway"** button will appear at the bottom.
3. Click **"Run anyway"**.

That's it! SmartScreen only blocks the app once. After the first launch, it will open normally.

<details>
<summary>💡 Why does this happen?</summary>

SmartScreen flags executables that have not been signed with a Microsoft Extended Validation (EV) Code Signing Certificate. These certificates cost several hundred dollars per year and require a registered business entity. Independent developers distributing free, open-source tools are rarely able to justify this cost. The warning does **not** indicate a virus — it simply means Microsoft hasn't seen this specific file before.

</details>

---

### 🪟 Windows — Firewall Prompt

You may also see a **Windows Firewall** popup on first launch:

> **"Do you want to allow this app to make changes?"**

**How to handle:**

1. Check both boxes (Private and Public networks).
2. Click **"Allow access"**.

The app runs a local Streamlit web server on `127.0.0.1:8501` — it needs permission to "talk to itself." No data is sent to any external server other than your Canvas LMS instance.

---

### 🍎 macOS — Gatekeeper Warning

When you open the `.app` for the first time, macOS Gatekeeper may display:

> **"'Canvas Downloader' can't be opened because Apple cannot check it for malicious software."**

**How to bypass (Method 1 — Recommended):**

1. **Right-click** (or Control-click) on `Canvas Downloader.app`.
2. Select **"Open"** from the context menu.
3. A new dialog will appear with an **"Open"** button — click it.

macOS remembers your choice. The app will open normally from now on.

---

### 🍎 macOS — "App is Damaged" Error

In some cases — especially if you downloaded the app via a browser — macOS may
display a more aggressive error:

> **"'Canvas Downloader.app' is damaged and can't be opened. You should move it to the Trash."**

**The app is NOT damaged.** macOS applies a "quarantine" flag to files downloaded from the internet, and unsigned apps trigger this false positive.

**How to fix (Terminal command):**

1. Open **Terminal** (search for it in Spotlight with `⌘ + Space`).
2. Run the following command, adjusting the path if needed:

```bash
xattr -cr /path/to/Canvas\ Downloader.app
```

For example, if the app is on your Desktop:

```bash
xattr -cr ~/Desktop/Canvas\ Downloader.app
```

3. Now double-click the app normally — it will launch without error.

<details>
<summary>💡 What does this command do?</summary>

`xattr -cr` removes **all extended attributes** from the `.app` bundle recursively. The key attribute being removed is `com.apple.quarantine`, which macOS automatically applies to any file downloaded from the internet. For unsigned applications, this quarantine flag causes Gatekeeper to reject the bundle entirely. The `-c` flag clears all attributes and `-r` processes the entire `.app` directory tree.

</details>

---

### 🍎 macOS — System Preferences Bypass (Alternative)

If the right-click method doesn't work, you can also allow the app via System Settings:

1. Open **System Settings** → **Privacy & Security**.
2. Scroll down to the **Security** section.
3. You should see a message saying `"Canvas Downloader" was blocked`.
4. Click **"Open Anyway"**.
5. Enter your password if prompted.

---

## Generating a Canvas API Token

The app requires a Canvas API Access Token to connect to your courses.

1. Log in to **Canvas** in your browser.
2. Go to **Account** → **Settings**.
3. Scroll down to **Approved Integrations**.
4. Click **"+ New Access Token"**.
5. Give it a name (e.g., "Canvas Downloader") and click **Generate Token**.
6. **Copy the token immediately** — you won't be able to see it again.
7. Paste it into the app when prompted.

> [!IMPORTANT]
> Use the **actual Canvas URL** (usually `https://schoolname.instructure.com`),
> not your school's login portal URL. Check the address bar **after** logging in to find it.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| App doesn't open at all | Try running from Terminal/Command Prompt to see error messages |
| "Unauthorized" error | Your API token may be expired — generate a new one |
| Downloads are slow | Canvas rate-limits API requests; the app retries automatically |
| Conversions fail (macOS) | Ensure Microsoft Office is installed for Word/Excel/PDF conversion |
| Video conversion fails | FFmpeg is bundled; if issues persist, run from source with `pip install moviepy` |

---

## Running from Source (Advanced)

If you prefer not to use the pre-built executable:

```bash
# Clone the repository
git clone https://github.com/birkls/Canvas_LMS_batch_file_downloader.git
cd Canvas_LMS_batch_file_downloader

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate       # macOS/Linux
# .venv\Scripts\activate        # Windows

# Install dependencies
pip install -r requirements.txt

# Launch
python start.py
```

---

<p align="center">
  <strong>Canvas Downloader</strong> is open-source software under the MIT License.<br>
  <a href="https://github.com/birkls/Canvas_LMS_batch_file_downloader">View Source on GitHub</a>
</p>
