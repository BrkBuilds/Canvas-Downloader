# Canvas Downloader

<p align="center">
  <img src="assets/icon.png" width="150" alt="Canvas Downloader Logo">
</p>

This application allows students to batch download files and modules from Canvas LMS courses. It mirrors the exact module structure of your courses on your local drive, ensuring you have offline access to all your study materials.

<p align="center">
  <img src="assets/screenshot_selection.png" width="48%" />
  <img src="assets/screenshot_download.png" width="48%" />
</p>

## Features
*   **Save Hours of Clicking**: Download *all* files from a course in seconds. No more clicking "download" on every single PDF.
*   **Stay Organized**: Automatically creates folders that match your Canvas Modules. Perfect for exam prep!
*   **Offline Access**: Get all your materials on your hard drive so you can study without internet.
*   **Downloads Everything**: Supports Files, Modules, Panopto Videos, Pages, and External Links.
*   **Always Up-to-Date**: New courses added to your Canvas account appear automatically in the app.
*   **Study Mode**: Use the "Pdf & Powerpoint only" filter to download only the most important study materials (skips everything else).
*   **Smart & Robust**: Skips files you can't access and retries automatically if the connection fails.
*   **Secure**: Runs locally on your machine. Your token is saved securely on your own computer.

### Security Warnings (Important!)
*   **"Windows protected your PC" (SmartScreen)**:
    *   If you download the `.exe` version, Windows might try to block it because it's made by a student, not a corporation.
    *   **Solution**: Click **"More info"** and then **"Run anyway"**.
*   **Firewall Popup**:
    *   When the app starts, Windows Firewall might ask for permission.
    *   **Why?**: The app runs a small local "web server" to show the UI. It needs permission to "talk" to itself.
    *   **Solution**: Check the boxes and click **"Allow access"**. It is completely safe.

## Installation & Running

### For Users (Run from Code)
Since this is a Python application, you can run it directly from the source code on Windows, Mac, or Linux.

**Prerequisites:**
1.  **Install Python 3**: Download from [python.org](https://www.python.org/downloads/). *Ensure you check "Add Python to PATH" during installation.*

**Steps:**
1.  **Clone or Download**: Click the green "<> Code" button above and select "Download ZIP" (or `git clone` this repo).
2.  **Unzip**: Extract the folder.
3.  **Install Requirements**:
    Open your terminal/command prompt in the folder and run:
    ```bash
    pip install -r requirements.txt
    ```
4.  **Launch**:
    Run the start script:
    ```bash
    python start.py
    ```
    The application will automatically launch in your default web browser.

## How to use Canvas Downloader

### Step 1: Authentication
1.  Open the app.
2.  **Enter your Canvas URL**:
    *   **Crucial**: You must use the *actual* Canvas URL, not your school's login portal.
    *   **How to find it**: Log in to Canvas in your browser. Look at the address bar **after** you are logged in.
    *   It often looks like `https://schoolname.instructure.com` (even if you went to `canvas.school.edu` to get there).
    *   Copy that URL and paste it into the app.
3.  **Get an API Token**:
    *   Go to **Account** -> **Settings** on Canvas.
    *   Scroll to **Approved Integrations**.
    *   Click **+ New Access Token**.
    *   Copy the long string and paste it into the app.
4.  Click **"Validate & Save Token"**.

### Step 2: Select Courses
1.  You will see a list of your courses.
2.  Select the ones you want to download (or click "Select All").
3.  Click **"Continue"**.

### Step 3: Download
1.  Choose your **Download Structure**:
    *   **With subfolders**: Keeps files organized exactly like in Canvas Modules (Recommended).
    *   **Flat**: Puts all files for a course into one big folder.
2.  Choose a **Destination Folder** on your computer.
3.  Click **"Confirm and Download"**.
4.  Wait for the magic to happen! 🪄

## What do the files in the project folder do?

*   `start.py`: The "Launcher" script that starts the system.
*   `app.py`: The visual interface you see in the browser.
*   `canvas_logic.py`: The "Brain" that talks to Canvas and handles downloads.
*   `translations.py`: Contains all text in English and Danish.
*   `requirements.txt`: List of tools the app needs.

## Common Issues & Troubleshooting

*   **"Unauthorized" Error**:
    *   If you see an error saying "unauthorized", your token might be expired, or you might be downloading too fast. The app now has "smart retries" to handle this, so just try again.
*   **White Screen**:
    *   If the browser window turns white and doesn't load, simply **refresh the page** (F5 or Cmd+R) or close the tab and reopen the link shown in the black "Mother" window.
*   **Download Speed**:
    *   To be safe and avoid getting blocked by Canvas, the app downloads 2 files at a time. Large courses might take a minute or two. Grab a coffee! ☕

## Under the Hood: Technical Overview

This application is built as a hybrid local web app to combine the power of Python with a modern UI.

### Architecture
*   **Frontend**: Built with **Streamlit**, providing a responsive and clean web interface.
*   **Launcher**: A lightweight **Tkinter** wrapper (`start.py`) that manages the Streamlit server process in a background thread, giving users a simple "double-click" experience without needing to manage command-line servers manually.
*   **Canvas Integration**: Uses the **CanvasAPI** library to interact with the LMS. It handles pagination, rate limiting, and object retrieval (Files, Pages, Modules).

### Key Technical Features
*   **Asynchronous I/O**: The core downloader (`canvas_logic.py`) utilizes `asyncio` and `aiohttp`. This allows the app to download multiple files in parallel (concurrency limited to prevent API bans), significantly speeding up large course traversals compared to synchronous requests.
*   **Resiliency Patterns**:
    *   **Smart Retries**: Implements exponential backoff for HTTP 429 (Rate Limit) and 5xx errors.
    *   **Conflict Resolution**: Automatically renames files if duplicates exist (e.g., `Exam (1).pdf`) to prevent overwriting.
    *   **Sanitization**: Cleans filenames of illegal characters to ensure cross-platform compatibility (Windows/Mac/Linux).

## Security
*   **Local Execution**: The app runs entirely on your local machine (`localhost`).
*   **Token Safety**: Your API Token is stored locally in `canvas_downloader_settings.json` and is **never** sent to any external server other than the official Canvas API for authentication.

## License
MIT License. Feel free to modify and use this for your own studies!
